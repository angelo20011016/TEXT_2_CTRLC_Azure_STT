# test_audio_file.py

from faster_whisper import WhisperModel
from scipy.io.wavfile import read as read_wav
import numpy as np

# --- 設定 (必須與主程式的成功配置一致) ---
MODEL_SIZE = "medium"
DEVICE = "cuda"
COMPUTE_TYPE = "int8"  # 使用我們確認過能成功載入的 int8 模式

# --- ★★★ 請確認這個路徑是您要測試的清晰音訊檔 ★★★ ---
AUDIO_FILE_PATH = r"D:\Projects\TEXT_2_CTRLC\debug_audio_20250727-122554.wav"

def main():
    """主測試函式"""
    print("--- 開始獨立音訊檔案測試 ---")

    # 1. 載入模型
    try:
        print(f"正在載入模型: {MODEL_SIZE} (device={DEVICE}, compute={COMPUTE_TYPE})")
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        print("模型載入成功！")
    except Exception as e:
        print(f"錯誤：模型載入失敗！ {e}")
        return

    # 2. 讀取音訊檔案
    try:
        print(f"正在讀取音訊檔案: {AUDIO_FILE_PATH}")
        # read_wav 會回傳取樣率和音訊數據 (一個 NumPy 陣列)
        samplerate, data = read_wav(AUDIO_FILE_PATH)
        print(f"音訊檔案讀取成功！取樣率: {samplerate}, 數據長度: {len(data)}")

        # 檢查取樣率是否為 16000，如果不是，Whisper 可能會出錯
        if samplerate != 16000:
            print(f"警告：音訊取樣率為 {samplerate}Hz，並非模型建議的 16000Hz。這可能會影響辨識結果。")

    except FileNotFoundError:
        print(f"錯誤：找不到檔案！請確認路徑是否正確: {AUDIO_FILE_PATH}")
        return
    except Exception as e:
        print(f"錯誤：讀取音訊檔案時發生問題！ {e}")
        return

    # 3. 準備音訊數據 (這是至關重要的一步)
    # 讀取到的 WAV 數據通常是 int16 型別，範圍在 -32768 到 32767 之間
    # Whisper 模型需要 float32 型別，且數值範圍在 -1.0 到 1.0 之間
    # 因此，我們需要進行型別轉換和「標準化」(Normalization)
    print("正在將音訊數據轉換為模型需要的 float32 格式...")
    audio_normalized = data.astype(np.float32) / 32768.0

    # 4. 執行辨識
    try:
        print("正在傳送音訊至模型進行辨識...")
        segments, info = model.transcribe(audio_normalized, beam_size=5, language="zh")

        print(f"辨識完成！偵測到的語言: '{info.language}'，機率: {info.language_probability:.2f}")

        result_text = "".join(segment.text for segment in segments).strip()

        print("\n--- 辨識結果 ---")
        if result_text:
            print(result_text)
        else:
            print("(辨識結果為空)")
        print("--------------------")

    except Exception as e:
        print(f"錯誤：在辨識過程中發生問題！ {e}")
        return

if __name__ == "__main__":
    main()