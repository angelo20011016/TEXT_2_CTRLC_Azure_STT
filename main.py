import sys
import threading
import time
import queue
import os

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from pynput import keyboard
import numpy as np
import sounddevice as sd
import azure.cognitiveservices.speech as speechsdk

# --- 全域設定 ---
HOTKEY = "<alt>+c" # 啟動/停止錄音的熱鍵

# --- 錄音設定 ---
# 請根據您的設備和環境校準這些值，這是解決辨識結果為空的核心！
# 播放 main.py 錄製的 debug_audio_*.wav 檔案來判斷是否需要調整。
SILENCE_THRESHOLD = 3000 # 靜音閾值：音量低於此值會被認為是靜音。如果您的聲音較小或麥克風較遠，請降低此值（例如：1500, 1000, 500）。
SILENCE_DURATION = 2   # 靜音持續時間：持續靜音超過此時間，會自動停止錄音。如果說話有較長停頓，請增加此值（例如：3, 4）。
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION = 0.2   # 音訊處理塊的時長（秒）。

class Communicate(QObject):
    # 用於跨執行緒通訊的信號
    hotkey_activated = Signal()
    recording_status_changed = Signal(str)
    transcription_finished = Signal(str)

class KeyListenerThread(threading.Thread):
    """
    獨立執行緒監聽全域熱鍵，不阻塞主 UI。
    """
    def __init__(self, comm: Communicate):
        super().__init__(daemon=True)
        self.comm = comm
        self.listener = None

    def run(self):
        # 設置熱鍵監聽
        hotkey = keyboard.HotKey(
            keyboard.HotKey.parse(HOTKEY),
            self.on_activate
        )
        with keyboard.Listener(
                on_press=self.for_canonical(hotkey.press),
                on_release=self.for_canonical(hotkey.release)) as self.listener:
            self.listener.join()

    def on_activate(self):
        # 熱鍵被按下時發送信號
        self.comm.hotkey_activated.emit()

    def for_canonical(self, f):
        return lambda k: f(self.listener.canonical(k))

    def stop(self):
        # 停止熱鍵監聽
        if self.listener:
            self.listener.stop()

class RecorderThread(threading.Thread):
    """
    獨立執行緒處理音訊錄製和 Azure 語音辨識。
    """
    def __init__(self, comm: Communicate, speech_config, audio_config):
        super().__init__(daemon=True)
        self.comm = comm
        self.speech_config = speech_config
        self.audio_config = audio_config
        self.stop_event = threading.Event()
        self.speech_recognizer = None
        self.push_stream = None

    def force_stop(self):
        """外部調用強制停止錄音"""
        print("收到強制停止信號！")
        self.stop_event.set()

    def run(self):
        self.comm.recording_status_changed.emit("正在錄音... (再次按熱鍵可手動停止)")
        
        # 創建 PushAudioInputStream
        self.push_stream = speechsdk.audio.PushAudioInputStream()
        self.audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        self.speech_recognizer = speechsdk.SpeechRecognizer(speech_config=self.speech_config, audio_config=self.audio_config)

        # 連接辨識結果事件
        self.speech_recognizer.recognized.connect(self.recognized_cb)
        self.speech_recognizer.session_started.connect(lambda evt: print('SESSION STARTED: {}'.format(evt)))
        self.speech_recognizer.session_stopped.connect(lambda evt: print('SESSION STOPPED {}'.format(evt)))
        self.speech_recognizer.canceled.connect(self.canceled_cb)

        # 開始連續辨識
        self.speech_recognizer.start_continuous_recognition_async().get()

        q = queue.Queue() # 用於音訊回調函數和主錄音循環之間的數據傳輸

        def audio_callback(indata, frames, time, status):
            """Sounddevice 回調函數，將音訊數據放入隊列並寫入 PushAudioInputStream"""
            if status:
                print(f"音訊回調狀態警告: {status}", file=sys.stderr)
            q.put(indata.copy()) # 將音訊數據複製後放入隊列
            # 將音訊數據寫入 PushAudioInputStream
            # 注意：indata 是 float32，需要轉換為 int16
            audio_bytes = (indata * 32767).astype(np.int16).tobytes()
            self.push_stream.write(audio_bytes)

        try:
            # 啟動音訊輸入流
            # 移除了 buffersize 參數，以避免 'unexpected keyword argument' 錯誤
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                 callback=audio_callback, 
                                 blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
                                 dtype='float32'): 
                print("錄音開始，等待語音輸入...")
                silence_start_time = None
                
                # 錄音主循環，直到收到停止事件或偵測到靜音
                while not self.stop_event.is_set():
                    try:
                        audio_chunk = q.get(timeout=0.1) # 從隊列獲取音訊塊
                        
                        # 計算當前音訊塊的音量 (用於靜音偵測)
                        volume_norm = np.linalg.norm(audio_chunk) * 1000 

                        # 靜音偵測邏輯
                        if volume_norm > SILENCE_THRESHOLD:
                            silence_start_time = None # 有聲音，重置靜音計時
                        else:
                            if silence_start_time is None:
                                silence_start_time = time.time() # 開始計時靜音
                            else:
                                if time.time() - silence_start_time > SILENCE_DURATION:
                                    print(f"偵測到持續靜音 {SILENCE_DURATION} 秒，自動停止錄音。")
                                    break # 靜音時間過長，停止錄音
                    except queue.Empty:
                        # 隊列暫時為空，繼續等待
                        continue
            
            print("錄音結束，準備辨識。")
            # 停止 PushAudioInputStream
            self.push_stream.close()
            # 停止連續辨識
            self.speech_recognizer.stop_continuous_recognition_async().get()

        except Exception as e:
            error_msg = f"錄音/辨識出錯: {e}"
            print(error_msg)
            self.comm.recording_status_changed.emit(error_msg)
            self.comm.transcription_finished.emit("")

    def recognized_cb(self, evt):
        """Azure Speech SDK 辨識結果回調"""
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print("辨識結果: {}".format(evt.result.text))
            self.comm.transcription_finished.emit(evt.result.text)
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("未辨識到語音。")
            self.comm.transcription_finished.emit("")

    def canceled_cb(self, evt):
        """Azure Speech SDK 取消事件回調"""
        print("取消: {}".format(evt.reason))
        if evt.reason == speechsdk.CancellationReason.Error:
            print("取消錯誤: {}".format(evt.error_details))
            self.comm.recording_status_changed.emit(f"辨識取消錯誤: {evt.error_details}")
        self.comm.transcription_finished.emit("")

class MainWindow(QWidget):
    """
    主視窗類，負責 UI 和各個執行緒的協調。
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STT for Hotkey")
        self.is_recording = False
        self.recorder_thread = None
        self.key_listener_thread = None

        # UI 佈局和元件
        self.layout = QVBoxLayout()
        self.model_status_label = QLabel("模型狀態：正在初始化 Azure Speech SDK...")
        self.hotkey_status_label = QLabel("熱鍵狀態：尚未啟動")
        self.process_status_label = QLabel("流程狀態：待機")
        self.result_label = QLabel("辨識結果：")
        
        self.layout.addWidget(self.model_status_label)
        self.layout.addWidget(self.hotkey_status_label)
        self.layout.addWidget(self.process_status_label)
        self.layout.addWidget(self.result_label)
        self.setLayout(self.layout)

        # 創建通訊對象並連接信號槽
        self.comm = Communicate()
        
        self.comm.hotkey_activated.connect(self.on_hotkey_activated_slot)
        self.comm.recording_status_changed.connect(self.on_status_changed)
        self.comm.transcription_finished.connect(self.on_transcription_finished)

        # 初始化 Azure Speech SDK 配置
        self.init_azure_speech_config()

    def init_azure_speech_config(self):
        try:
            speech_key = os.environ.get("SPEECH_KEY")
            speech_region = os.environ.get("SPEECH_REGION")
            if not speech_key or not speech_region:
                raise ValueError("請設定環境變數 SPEECH_KEY 和 SPEECH_REGION")

            self.speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
            self.speech_config.speech_recognition_language = "zh-TW" # 或 "zh-CN", "en-US" 等

            # 使用 PushAudioInputStream 實現實時音訊流
            self.audio_config = speechsdk.AudioConfig(use_default_microphone=True) # 這裡可以改為 PushAudioInputStream

            self.model_status_label.setText("Azure Speech SDK 已初始化。")
            self.hotkey_status_label.setText(f"熱鍵狀態：正在監聽 ({HOTKEY})")
            # 啟動熱鍵監聽執行緒
            self.key_listener_thread = KeyListenerThread(comm=self.comm)
            self.key_listener_thread.start()

        except Exception as e:
            error_msg = f"Azure Speech SDK 初始化失敗: {e}\n請檢查環境變數和網路連線。"
            print(error_msg)
            self.model_status_label.setText(error_msg)
            self.hotkey_status_label.setText("熱鍵狀態：無法啟動 (Azure SDK 初始化失敗)")
            self.process_status_label.setText("流程狀態：錯誤")

    @Slot()
    def on_hotkey_activated_slot(self):
        """熱鍵被按下時的處理邏輯"""
        if self.is_recording:
            # 如果正在錄音，則強制停止錄音
            if self.recorder_thread and self.recorder_thread.is_alive():
                self.recorder_thread.force_stop()
        else:
            # 如果 Azure Speech SDK 尚未初始化，則不啟動錄音
            if not hasattr(self, 'speech_config') or not self.speech_config:
                print("Azure Speech SDK 尚未初始化完成，請稍候。")
                self.process_status_label.setText("流程狀態：Azure SDK 未就緒")
                return
            # 啟動錄音
            self.is_recording = True
            self.result_label.setText("辨識結果：") # 清空上次結果
            self.recorder_thread = RecorderThread(self.comm, self.speech_config, self.audio_config)
            self.recorder_thread.start()

    @Slot(str)
    def on_status_changed(self, status):
        """更新流程狀態標籤"""
        self.process_status_label.setText(f"流程狀態：{status}")

    @Slot(str)
    def on_transcription_finished(self, text):
        """辨識完成後的回調，更新結果並複製到剪貼簿"""
        self.result_label.setText(f"辨識結果：{text}")
        self.process_status_label.setText("流程狀態：待機")
        self.is_recording = False
        if text:
            # 將辨識結果複製到剪貼簿
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.process_status_label.setText("流程狀態：已複製到剪貼簿！")
            # 短暫顯示「已複製」訊息後恢復待機
            QTimer.singleShot(2000, lambda: self.process_status_label.setText("流程狀態：待機"))
        
    def closeEvent(self, event):
        """視窗關閉事件處理，停止所有執行緒"""
        if self.key_listener_thread:
            self.key_listener_thread.stop()
        if self.recorder_thread and self.recorder_thread.is_alive():
            self.recorder_thread.force_stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())