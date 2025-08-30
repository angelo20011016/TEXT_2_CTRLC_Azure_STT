import sys
import threading
import time
import queue
import os
from dotenv import load_dotenv

from PySide6.QtCore import QObject, Signal, Slot, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PySide6.QtMultimedia import QSoundEffect
from pynput import keyboard
import numpy as np
import sounddevice as sd
import azure.cognitiveservices.speech as speechsdk
from scipy.io.wavfile import write as write_wav

# --- 全域設定 ---
HOTKEY = "<alt>+c"

# --- 錄音設定 ---
DEVICE_ID = 1
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 2
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_DURATION = 0.2

def generate_ding_sound(file_name="ding.wav", freq=880, duration_s=0.15, volume=0.25):
    if os.path.exists(file_name):
        return
    try:
        print(f"Generating '{file_name}' sound file...")
        sample_rate = 44100
        t = np.linspace(0., duration_s, int(sample_rate * duration_s), endpoint=False)
        amplitude = np.iinfo(np.int16).max * volume
        data = amplitude * np.sin(2. * np.pi * freq * t)
        write_wav(file_name, sample_rate, data.astype(np.int16))
    except Exception as e:
        print(f"Could not generate sound file: {e}")

class Communicate(QObject):
    hotkey_activated = Signal()
    recording_status_changed = Signal(str)
    transcription_finished = Signal(str)

class KeyListenerThread(threading.Thread):
    def __init__(self, comm: Communicate):
        super().__init__(daemon=True)
        self.comm = comm
        self.listener = None

    def run(self):
        hotkey = keyboard.HotKey(
            keyboard.HotKey.parse(HOTKEY),
            self.on_activate
        )
        with keyboard.Listener(
                on_press=self.for_canonical(hotkey.press),
                on_release=self.for_canonical(hotkey.release)) as self.listener:
            self.listener.join()

    def on_activate(self):
        self.comm.hotkey_activated.emit()

    def for_canonical(self, f):
        return lambda k: f(self.listener.canonical(k))

    def stop(self):
        if self.listener:
            self.listener.stop()

class RecorderThread(threading.Thread):
    def __init__(self, comm: Communicate, speech_config, audio_config):
        super().__init__(daemon=True)
        self.comm = comm
        self.speech_config = speech_config
        self.audio_config = audio_config
        self.stop_event = threading.Event()
        self.speech_recognizer = None
        self.push_stream = None

    def force_stop(self):
        print("收到強制停止信號！")
        self.stop_event.set()

    def run(self):
        self.comm.recording_status_changed.emit("正在錄音... (再次按熱鍵可手動停止)")
        
        self.push_stream = speechsdk.audio.PushAudioInputStream()
        self.audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        self.speech_recognizer = speechsdk.SpeechRecognizer(speech_config=self.speech_config, audio_config=self.audio_config)

        self.speech_recognizer.recognized.connect(self.recognized_cb)
        self.speech_recognizer.session_started.connect(lambda evt: print(f'SESSION STARTED: {evt}'))
        self.speech_recognizer.session_stopped.connect(lambda evt: print(f'SESSION STOPPED {evt}'))
        self.speech_recognizer.canceled.connect(self.canceled_cb)

        self.speech_recognizer.start_continuous_recognition_async().get()

        q = queue.Queue()

        def audio_callback(indata, frames, time, status):
            if status:
                print(f"音訊回調狀態警告: {status}", file=sys.stderr)
            q.put(indata.copy())
            audio_bytes = (indata * 32767).astype(np.int16).tobytes()
            self.push_stream.write(audio_bytes)

        try:
            with sd.InputStream(device=DEVICE_ID, samplerate=SAMPLE_RATE, channels=CHANNELS,
                                 callback=audio_callback, 
                                 blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
                                 dtype='float32'): 
                print("錄音開始，等待語音輸入...")
                silence_start_time = None
                
                while not self.stop_event.is_set():
                    try:
                        audio_chunk = q.get(timeout=0.1)
                        volume_norm = np.linalg.norm(audio_chunk) * 1000 

                        if volume_norm > SILENCE_THRESHOLD:
                            silence_start_time = None
                        else:
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            else:
                                if time.time() - silence_start_time > SILENCE_DURATION:
                                    print(f"偵測到持續靜音 {SILENCE_DURATION} 秒，自動停止錄音。 সন")
                                    break
                    except queue.Empty:
                        continue
            
            print("錄音結束，準備辨識。")
            self.push_stream.close()
            self.speech_recognizer.stop_continuous_recognition_async().get()

        except Exception as e:
            error_msg = f"錄音/辨識出錯: {e}"
            print(error_msg)
            self.comm.recording_status_changed.emit(error_msg)
            self.comm.transcription_finished.emit("")

    def recognized_cb(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print(f"辨識結果: {evt.result.text}")
            self.comm.transcription_finished.emit(evt.result.text)
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("未辨識到語音。")
            self.comm.transcription_finished.emit("")

    def canceled_cb(self, evt):
        print(f"取消: {evt.reason}")
        if evt.reason == speechsdk.CancellationReason.Error:
            print(f"取消錯誤: {evt.error_details}")
            self.comm.recording_status_changed.emit(f"辨識取消錯誤: {evt.error_details}")
        self.comm.transcription_finished.emit("")

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STT for Hotkey")
        self.is_recording = False
        self.recorder_thread = None
        self.key_listener_thread = None

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

        self.comm = Communicate()
        
        self.comm.hotkey_activated.connect(self.on_hotkey_activated_slot)
        self.comm.recording_status_changed.connect(self.on_status_changed)
        self.comm.transcription_finished.connect(self.on_transcription_finished)

        self.setup_sound()
        self.init_azure_speech_config()

    def setup_sound(self):
        generate_ding_sound()
        self.sound_effect = QSoundEffect()
        self.sound_effect.setSource(QUrl.fromLocalFile("ding.wav"))
        self.sound_effect.setVolume(0.25)

    def init_azure_speech_config(self):
        try:
            load_dotenv()
            speech_key = os.environ.get("SPEECH_KEY")
            speech_region = os.environ.get("SPEECH_REGION")
            if not speech_key or not speech_region:
                raise ValueError("請在 .env 檔案中設定 SPEECH_KEY 和 SPEECH_REGION")

            self.speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
            self.speech_config.speech_recognition_language = "zh-TW"

            self.audio_config = speechsdk.AudioConfig(use_default_microphone=True)

            self.model_status_label.setText("Azure Speech SDK 已初始化。")
            self.hotkey_status_label.setText(f"熱鍵狀態：正在監聽 ({HOTKEY})")
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
        if self.is_recording:
            if self.recorder_thread and self.recorder_thread.is_alive():
                self.recorder_thread.force_stop()
        else:
            if not hasattr(self, 'speech_config') or not self.speech_config:
                print("Azure Speech SDK 尚未初始化完成，請稍候。")
                self.process_status_label.setText("流程狀態：Azure SDK 未就緒")
                return
            self.is_recording = True
            self.result_label.setText("辨識結果：")
            self.sound_effect.play()
            self.recorder_thread = RecorderThread(self.comm, self.speech_config, self.audio_config)
            self.recorder_thread.start()

    @Slot(str)
    def on_status_changed(self, status):
        self.process_status_label.setText(f"流程狀態：{status}")

    @Slot(str)
    def on_transcription_finished(self, text):
        self.sound_effect.play()
        self.result_label.setText(f"辨識結果：{text}")
        self.process_status_label.setText("流程狀態：待機")
        self.is_recording = False
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.process_status_label.setText("流程狀態：已複製到剪貼簿！")
            QTimer.singleShot(2000, lambda: self.process_status_label.setText("流程狀態：待機"))
        
    def closeEvent(self, event):
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
