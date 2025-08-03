# TEXT_2_CTRLC - Azure STT 版本

這是一個基於 Python 的桌面應用程式，它允許您使用熱鍵啟動語音轉文字 (Speech-to-Text, STT) 功能。語音辨識結果會自動複製到您的剪貼簿中，方便您快速貼上到任何應用程式。此版本已將 STT 引擎替換為 Microsoft Azure Speech Service，提供更強大和可擴展的語音辨識能力。

## 功能特色

*   **熱鍵觸發**：透過自定義熱鍵快速啟動/停止錄音。
*   **Azure STT 整合**：利用 Azure Speech Service 進行高效且準確的語音辨識。
*   **自動複製到剪貼簿**：辨識完成後，文字結果會自動複製到剪貼簿。
*   **靜音偵測**：自動偵測靜音並停止錄音，提升使用體驗。

## 先決條件

在運行此應用程式之前，請確保您已安裝以下軟體：

*   Python 3.8 或更高版本
*   `pip` (Python 包管理器)
*   Microsoft Azure 帳戶，並已啟用 Speech Service。您需要獲取 **訂閱金鑰 (Subscription Key)** 和 **服務區域 (Service Region)**。

## 安裝步驟

1.  **克隆儲存庫**：
    ```bash
    git clone https://github.com/您的GitHub用戶名/您的儲存庫名稱.git
    cd 您的儲存庫名稱
    ```
    (請將 `您的GitHub用戶名` 和 `您的儲存庫名稱` 替換為實際值)

2.  **創建並激活虛擬環境 (推薦)**：
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **安裝依賴項**：
    ```bash
    pip install -r requirements.txt
    ```

## 配置 Azure 憑證

為了讓應用程式能夠連接到 Azure Speech Service，您需要設定兩個環境變數：

*   `SPEECH_KEY`：您的 Azure Speech Service 訂閱金鑰。
*   `SPEECH_REGION`：您的 Azure Speech Service 區域 (例如：`eastus`, `southeastasia` 等)。

**Windows (命令提示字元)**：
```cmd
set SPEECH_KEY=您的訂閱金鑰
set SPEECH_REGION=您的區域
```
**Windows (PowerShell)**：
```powershell
$env:SPEECH_KEY="您的訂閱金鑰"
$env:SPEECH_REGION="您的區域"
```
**macOS/Linux (Bash/Zsh)**：
```bash
export SPEECH_KEY="您的訂閱金鑰"
export SPEECH_REGION="您的區域"
```
**提示**：為了讓這些環境變數在每次開啟終端機時都自動載入，您可以將 `export` 命令添加到您的 shell 配置文件中（例如 `~/.bashrc`, `~/.zshrc` 或 `~/.profile`）。

## 使用方法

1.  **運行應用程式**：
    ```bash
    python main.py
    ```
    應用程式啟動後，您會看到一個簡單的 GUI 視窗，顯示模型狀態和流程狀態。

2.  **使用熱鍵**：
    預設熱鍵是 `Alt + C`。
    *   按下 `Alt + C`：開始錄音。
    *   再次按下 `Alt + C`：手動停止錄音。
    *   應用程式也會在偵測到長時間靜音後自動停止錄音。

3.  **查看辨識結果**：
    語音辨識完成後，結果會顯示在 GUI 視窗中，並自動複製到剪貼簿。

## 故障排除

*   **"Azure Speech SDK 初始化失敗"**：請檢查您的 `SPEECH_KEY` 和 `SPEECH_REGION` 環境變數是否正確設定，以及您的網路連接是否正常。
*   **辨識結果為空或不準確**：
    *   檢查您的麥克風是否正常工作。
    *   調整 `main.py` 中的 `SILENCE_THRESHOLD` 和 `SILENCE_DURATION` 參數，以適應您的麥克風和環境噪音水平。
    *   確保 `SAMPLE_RATE` 和 `CHANNELS` 與您的麥克風設置匹配。

## 貢獻

歡迎對此專案提出貢獻！如果您有任何建議、錯誤報告或功能請求，請隨時提交 Issue 或 Pull Request。
