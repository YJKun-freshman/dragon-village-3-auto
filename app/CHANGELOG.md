# CHANGELOG — app

## v0.5.3 — 2026-11-11
### 發布
- 改成公開儲存庫：GitHub 上的舊儲存庫刪除，用目前的檔案重新建立（舊紀錄裡有個人 email 和交接文件）
- 內含 core v0.5.8（Meta 大 Skip 等廣告樣板）、fishing 的新進場樣板
### 跨模組修改
- （無）

## v0.5.2 — 2026-11-09
### 新增
- 開發測試任務「**關廣告測試**」（`app/demo.py` `AdTest`）：畫面上有廣告時按開始，只跑 `core.ads.AdCloser.close_until`（按鈕、移除廣告高級版、卡住按喇叭、Shift+Tab），不會自動走路或釣魚；按 F6 或時間到（預設 120 秒）停止
  - 開始時在日誌寫出目前是 9:16／16:9、看得到哪個關閉鈕、有沒有喇叭
  - 原因：使用者原本用「釣魚」測廣告，但釣魚開始時只等 5 秒、接著會自動走去釣魚場，測不到卡住時的處理，也可能在別的畫面亂走
### 跨模組修改
- （無）

## v0.5.1 — 2026-11-08
### 修改（由「戰鬥」對話修改）
- 功能樹順序：`Catalog.rebuild()` 改成照 `TASK_MODULES` 的順序，**同一個模組裡固定任務在前、自訂項目在後**
  - 原因：使用者要「討伐戰巡迴」排在「討伐戰」上面（原本自訂項目全部排在固定任務前面，巡迴跑到公會BOSS 下面）
  - 結果：戰鬥 › 討伐戰巡迴、討伐戰（瑪歛克…）、公會BOSS（…）；釣魚照舊在最後
  - 驗證：用使用者的 config.json 建 Catalog，順序正確；`items_values()` 不受影響
### 跨模組修改
- （無，這是被修改的一方）

## v0.5.0 — 2026-11-08
### 新增 ⚠ 介面新增（01 待辦 D、E，給戰鬥的「討伐戰巡迴」）
- **D**：同一個模組可以同時提供 `TEMPLATES` 和 `TASKS`（以前有 TEMPLATES 就忽略 TASKS）；路徑重複照舊略過並警告
- **E**：任務類別宣告 `needs_items = "raid"`（template_id）→ Runner 建立任務後設定 `task.items = {項目名稱: 已轉好型別的參數}`（順序 = 功能樹順序，用 `Catalog.items_values()`；開始時取一次）
- 驗證：假模組同時給 TEMPLATES＋TASKS，巡迴任務讀到瑪歛克、泰迪布羅各自的出招流程
### 修改
- `build.py`：`DATA_DIRS` 加 `core/templates`（關廣告樣板）
### 跨模組修改
- core v0.5.0：`Task.needs_items`、`Task.items`
- ui v0.4.2：`__version__` 改對（01 待辦 F）

## v0.4.2 — 2026-11-08
### 發布
- 重新打包給 exe 版使用者：內含 combat v0.4.8、fishing v0.5.3（app 程式沒有改）
- 說明：視窗標題和 Release 都用 app 的版本號，所以其他模組更新後要發布時，app 版本也要 +1
### 跨模組修改
- （無）

## v0.4.1 — 2026-11-07
### 修改（發布準備）
- `show_demo_tasks` 預設改成 False（「開發測試」任務不顯示；開發時在 config.json 設 true 或用 `--demo`）
### 修正
- 遊戲視窗縮到最小時，日誌每秒跳一次「已連接遊戲視窗」：監看執行緒在「不能用」時每秒重新連接，但縮到最小視窗還在、重連也沒用。
  改成只有視窗不見了（遊戲關掉）才重新找；縮到最小只在狀態列顯示原因（這個問題從 v0.1.0 就有）
### 跨模組修改
- core v0.4.1：新增 `Game.window_exists()`、`connect()` 同一視窗不重複寫日誌

## v0.4.0 — 2026-11-07
### 新增 ⚠ 介面變動（自訂戰鬥項目，見 02「📝 提案：自訂戰鬥項目」→「✅ 主程式合併的回覆」）
- `app/registry.py` 改寫成 `Catalog`：
  - 支援模組的 `TEMPLATES`（類型範本）；**有 TEMPLATES 的模組忽略它的 TASKS**（combat 的過渡 TASKS 不會重複）
  - 項目清單存在 `config.json` 的 `"custom_tasks": {template_id: [名稱, ...]}`；某類型第一次出現時用 `default_items` 建立，預設值寫進 `values`（已有值的路徑不覆蓋 → 使用者原本泰迪布羅、瑪歛克的設定保留）
  - 項目類別用模組的 `make_item(範本, 名稱)`（沒有就自己 `type(...)`）
  - 編輯：`add` / `rename` / `delete` / `move`；名稱規則：去空白後 1～20 字、不能有 `/` `\`、同類型不重複
  - 複製（`add` 帶 values）只保留新類型有的參數，並轉成正確型別
  - 改名：values、`last_task` 跟著改；刪除：values 一起刪
- 給 ui：任務 dict 多 `"editable": True`、`"group"`；`MainWindow(..., task_groups=[{"path", "id", "name"}], task_editor={add, rename, delete, move})`（用 `_accepts()` 檢查）
  - 回呼成功回傳 `(True, 訊息, 新的完整任務清單)`，失敗 `(False, 中文原因, None)`；執行中回傳 `(False, "執行中不能編輯", None)`
  - 成功後存設定檔、Runner 換成新的任務清單
- `Runner.set_tasks()`
### 已驗證（離線）
- 第一次建立預設項目、不覆蓋已存的值、新增／複製（跨類型只留共同參數）／改名（values、last_task 跟著）／刪除／上下移、名稱規則、重新啟動後清單保留；假介面走一次 task_editor
### 跨模組修改
- 介面約定：已在 02 寫回覆、更新 00 第 5.4 節
- combat：`TASKS` 可以保留（主程式會忽略），想改成空清單也可以

## v0.3.0 — 2026-11-07
### 新增 ⚠ 介面變動（設定選單，和 Tkinter外型一起訂，見 02「設定選單（定案）」）
- `MainWindow(..., settings={...})`（用 `_accepts()` 檢查，臨時介面不受影響）：
  `hotkeys`、`default_hotkeys`、`set_hotkeys`、`pause_hotkeys`、`list_windows`、`current_window`、`select_window`
- `app/hotkeys.py` 改寫：
  - 執行中可以重新註冊、暫停／恢復（指令排進熱鍵執行緒處理，因為 RegisterHotKey 只能由同一個執行緒取消）
  - `normalize()` / `validate_pair()`：F1～F24 可單獨用；字母、數字要有 Ctrl 或 Alt；修飾鍵順序 Ctrl+Alt+Shift；開始≠停止
  - 換熱鍵時新的鍵被佔用 → 保留原本的熱鍵並回傳中文原因；暫停中也會先試註冊確認可用
- 啟動時設定檔的熱鍵不合規則 → 改用預設 F5／F6 並在日誌提示；啟動訊息顯示實際熱鍵
- 改熱鍵成功 → 存設定檔、呼叫 ui 的 `set_hotkey_labels()`（有才呼叫）
- 選擇遊戲視窗：`Runner.list_windows()` / `current_window()` / `select_window()`；選了之後存標題到 `config.json` 的 `"game_window"`，之後有多個視窗時優先連它；換視窗後立刻 `set_game_status()`
- 執行中不能改熱鍵、不能換視窗（回傳中文原因）
### 已驗證（Linux，假介面）
- 規則檢查、套用、暫停／恢復、存設定檔、更新按鈕文字
### 待使用者實測（ui 做好設定視窗後）
- Windows 實機：改熱鍵後新熱鍵有效、舊熱鍵失效；錄製時按 F5 不會觸發開始；被佔用的鍵會提示；多個遊戲視窗時切換
### 跨模組修改
- 介面約定：已更新 `02_Tkinter外型.md`、`00_專案總覽.md` 第 5.4 節

## v0.2.2 — 2026-11-07
### 審查（主程式合併）
- 檢查 ui 對話做的 v0.2.0、v0.2.1 修改：符合設計，保留。`_accepts()` / `hasattr()` 檢查讓臨時介面仍可用
### 修正
- 關閉視窗時也儲存參數：原本只有按「開始」才存，改了參數沒執行就關掉會遺失。關閉時讀 `win.get_values()` 寫進設定檔
- 日誌清理也會刪 `logs\` 裡超過保留天數的 `.png` / `.jpg`（釣魚、戰鬥存的除錯截圖），避免一直累積
### 已驗證（Linux 虛擬螢幕＋離線遊戲＋正式介面 customtkinter 6.0）
- 正式介面載入、上次選的任務自動選取、開始／進度／結束、狀態列、關閉時存視窗狀態與參數
### 修正
- `啟動.bat` 雙擊後只有黑色視窗、程式沒啟動：檔案被存成 LF 換行（v0.2.0 修改時），含中文的 .bat 用 LF 時 Windows 命令列會讀錯指令。改回 CRLF
### 實機測試（2026-11-07）✅
- 正式介面＋戰鬥（泰迪布羅、瑪歛克）＋釣魚（連續 29 次成功、含看廣告補魚餌）都正常；停止、日誌、F5/F6 全域熱鍵（正式介面）、重開後記住視窗大小 ✅
### 跨模組修改
- （無）

## v0.2.1 — 2026-11-07（由「Tkinter外型」對話修改）
### 新增
- 記住視窗大小、位置、精簡／完整模式：`config.json` 新增 `"window"`；啟動時傳 `MainWindow(window_state=...)`，關閉時存 `win.get_window_state()`（都用 `_accepts()` / `hasattr()` 檢查，臨時介面不受影響）
### 跨模組修改
- （無，本版本是被 ui 修改）

## v0.2.0 — 2026-11-06（由「Tkinter外型」對話修改）
### 新增 ⚠ 介面變動
- `registry.to_ui()`：每個參數多傳 `"widget"`（`Param.widget`，core v0.4.0）
- `main.py` 多傳兩個參數給 `MainWindow`（用 `_accepts()` 檢查，臨時介面不受影響）：
  - `sequence_tools={"parse", "to_text", "validate"}`：來自 `combat.sequence`，給出招流程編輯器做文字 ↔ 清單轉換、檢查（ui 不能 import combat）。沒有 combat 時傳 `None`
  - `on_open_logs`：開啟日誌資料夾（`<設定檔資料夾>\logs`）
- 根目錄 `requirements.txt` 加 `customtkinter>=5.2`（正式介面用）；`啟動.bat` 第一次執行的套件檢查加上 `customtkinter`
### 注意
- 沒裝 customtkinter 時，`load_ui()` 會記錄錯誤並改用臨時介面（原本的機制，不用改）
- PyInstaller 打包時要帶 customtkinter 的主題檔：`--collect-data customtkinter`
### 跨模組修改
- （無，本版本是被 ui 修改）

## v0.1.0 — 2026-11-05
### 新增
- `app/main.py`：程式進入點 `run()`。根目錄 `main.py` 只呼叫它；也可用 `python -m app`
- `app/registry.py`：收集 `combat.TASKS`、`fishing.TASKS`（模組還不存在就略過），檢查是 `Task` 子類別、有 `path`、路徑不重複，轉成 ui 用的資料
- `app/runner.py`：任務在背景執行緒執行，同時只跑一個
  - 開始前檢查遊戲視窗，不行就在日誌顯示原因
  - 任務拋出例外 → 日誌顯示錯誤（完整錯誤寫進日誌檔），程式不會當掉
  - 監看執行緒每秒檢查遊戲：自動連接、更新狀態列；執行中遊戲被關閉／縮到最小 → 停止任務並提示
  - 有多個遊戲視窗時使用第一個，並在日誌提示（之後可在 ui 加選擇）
- `app/hotkeys.py`：全域熱鍵（Windows `RegisterHotKey`），預設 F5 開始、F6 停止，可在 `config.json` 改（例：`"Ctrl+F5"`）。被佔用時日誌提示
- `app/config.py`：`config.json` 放程式旁邊，寫不進去改放 `%APPDATA%\龍村3自動腳本\`；記住每個任務的參數、上次選的任務；壞掉的設定檔改名 `.bad` 後用預設值
- `app/logs.py`：日誌同時顯示在介面和寫進 `logs\YYYY-MM-DD.log`，保留 7 天
- `app/fallback_ui.py`：**臨時介面**，方法與 `02_Tkinter外型.md` 約定相同；`ui/` 完成後自動改用正式介面
- `app/demo.py`：開發測試任務「背景點擊」「計數」（`config.json` 的 `show_demo_tasks`，開發期間預設開啟；**發布前要改成預設關閉**）
- 根目錄：`main.py`、`啟動.bat`

### 已驗證（虛擬螢幕＋離線遊戲）
- 參數輸入錯誤會提示且不能開始；開始／停止（0.2 秒內停下）；任務錯誤不會當掉；設定檔與日誌檔正確寫入

### 實機測試（2026-11-05）✅
- 自動連接遊戲、背景點擊任務、F5/F6 全域熱鍵（視窗沒有焦點時也有效）、停止立即生效、任務錯誤不會當掉

### 跨模組修改
- ui 介面約定補充（⚠ 介面變動，`ui/` 尚未開始所以不影響現有程式）：新增 `request_start()`、`request_stop()`、`selected` 參數，明確 `saved_values` 格式。已更新 `00_專案總覽.md` 5.4 節與 `02_Tkinter外型.md`
