# core — 共用底層

給「釣魚」「戰鬥」對話用的說明。介面約定見 `00_專案總覽.md` 第 5 節，版本紀錄見 `CHANGELOG.md`。

## 座標規則

- **一律用遊戲畫面的比例 0.0～1.0**（不含黑邊），左上 (0, 0)、右下 (1, 1)
- `game.capture()` 回傳「正規化畫面」：只有遊戲畫面、高度固定 1000（寬約 562），numpy BGR
- 樣板圖一律從正規化畫面裁 → 用截圖工具截就對了

## 基本用法

```python
from core.game import Game, GameNotReady

game = Game()
if not game.connect():
    print("找不到遊戲")

frame = game.capture()                                   # 截一次，下面重複用
m = game.find("fishing/templates/上鉤.png", region=(0.3, 0.6, 0.7, 0.9), frame=frame)
if m:
    game.click_match(m)                                  # m.x, m.y, m.w, m.h（比例）、m.score

game.click(0.5, 0.85)
game.long_press(0.5, 0.85, 1.5)
game.drag(0.2, 0.5, 0.8, 0.5, seconds=0.4)
game.scroll(0.5, 0.5, -2)                               # 滾輪往下 2 格（遊戲可用滾輪縮放）
game.key("shift", "tab")                                # 背景按鍵（v0.3.0，實機有效）
m = game.wait_for("combat/templates/結算.png", timeout=30)   # 超時或被停止 → None
game.wait_gone("combat/templates/讀取中.png", timeout=30)    # 消失 → True
b, g, r = game.pixel(0.5, 0.5)                            # 某點顏色
print(game.best_score("fishing/templates/上鉤.png"))      # 調 threshold 用
```

- 樣板路徑用**相對專案根目錄**的寫法（`"fishing/templates/xxx.png"`），exe 版也能用
- 盡量給 `region`：快 50 倍，也比較不會誤判
- 視窗不能用（關掉、縮到最小）時，`capture()` / `click()` 會丟 `GameNotReady`（訊息是中文，可直接顯示）。在任務裡不用接，app 會接住並顯示

## 多倍率、模糊（core v0.5.0）

```python
m = game.find(tpl, region=r, threshold=0.85, scales=(1.0, 1.08, 1.16, 1.26, 0.93), blur=5)
```
- `scales`：依序試，第一個達到門檻的就回傳。16:9 視窗時有些介面會放大 1.16～1.26 倍
- `blur`：畫面和樣板先模糊（奇數，例 5）。視窗大小不同、清晰度不同時比較穩
- 都是預設關閉；`find_all`、`best_score`、`wait_for`、`wait_gone` 也有

## 關廣告（core v0.5.0）

```python
from core.ads import AdCloser

ads = AdCloser(game, log=self.log, debug_name="釣魚")   # 一個任務建一個（「今天不再顯示」只勾一次）
ok = ads.close_until(done=self._is_main, timeout=45, extra=self._my_popups, debug_on_timeout="廣告卡住")
```
- `done(遊戲畫面)`：回到你的畫面了嗎。**看得到廣告關閉鈕時不算**（有些廣告只蓋住上半部）
- `extra(遊戲畫面)`：你自己的處理（例：釣魚魚卡的 X），回傳 `"acted"`／`"busy"`／`None`
- 自動處理：略過／Skip／各種 X、寬膠囊按右端 ✕、倒數 X 等 30 秒、移除廣告高級版彈窗、15 秒沒東西按送 Shift+Tab
- 16:9（`game.letterboxed`）時自動看整個視窗、點黑邊上的關閉鈕；整個視窗的畫面用 `game.capture_window()`、點擊用 `game.click_window()`

## 寫任務

```python
from core.task import Task, Param

class Fishing(Task):
    path = ("釣魚",)
    description = "自動釣魚"
    params = [
        Param("max_rounds", "釣魚次數上限", int, default=100, min=1, max=9999),
        Param("react_delay", "上鉤反應延遲(秒)", float, default=0.05, min=0, max=2),
        Param("bait", "魚餌", str, default="普通", choices=["普通", "高級"]),
        Param("sell", "背包滿時賣魚", bool, default=True, help="滑鼠移上去顯示的說明"),
    ]

    def run(self):
        for i in range(self.values["max_rounds"]):
            if self.should_stop():
                return
            self.set_progress(f"第 {i + 1}/{self.values['max_rounds']} 輪")
            self.log("拋竿")
            self.game.click(0.5, 0.85)
            if not self.sleep(1.0):          # 被停止會回傳 False
                return
```

- 參數值在 `self.values`，已經轉好型別、限制在 min/max 內
- 等待一律用 `self.sleep()` 或 `game.wait_for()`，按停止時會立刻中斷
- 想從很深的函式直接結束：`self.check_stop()`（停止時丟 `TaskStopped`）
- 在 `fishing/__init__.py` 寫 `TASKS = [Fishing]`

## 離線測試（不用開遊戲）

```python
game = Game.from_images("截圖/釣魚_連拍_1105_120000")   # 資料夾或檔案清單
task = Fishing(game, {"max_rounds": 3}, print)
task.run()
print(game.clicks)          # 離線模式點擊只記錄：[("click", x, y), ...]
```

`capture()` 會依檔名順序回傳每一張，最後一張之後一直停在最後一張（`loop=True` 會回到第一張）。

## 截圖工具

雙擊根目錄的 `capture.bat`（或 `python -m core.tools.capture_tool`）：

- **截圖**：輸入名稱按 Enter，存到 `截圖\`，存的是正規化畫面
- **連拍**：每 N 毫秒一張、連拍 M 秒，存到 `截圖\名稱_日期時間\`，檔名含毫秒（分析時機用）
- **框選**：在圖上拖曳 → 顯示 `region=(...)` 和中心點，可複製；輸入名稱、選資料夾（例 `fishing\templates`）→ 存成樣板
- **測試找圖**：選一張樣板，在目前畫面上框出找到的位置和分數
- **點擊／拖曳測試**：在預覽圖上點，會在背景送到遊戲
- **測速**：截圖＋正規化的平均時間

## 檔案

| 檔案 | 內容 |
|---|---|
| `game.py` | `Game`、`GameNotReady`（對外只要 import 這個和 `task.py`） |
| `task.py` | `Task`、`Param`、`TaskStopped` |
| `vision.py` | 找圖、`Match`、`imread`/`imwrite`（中文路徑） |
| `capture.py` | 截圖、去黑邊、正規化 |
| `input.py` | 背景點擊、長按、拖曳 |
| `window.py` | 找視窗 |
| `paths.py` | 資源／資料路徑（原始碼版、exe 版） |
| `_win32.py` | Windows API 宣告 |
| `tools/capture_tool.py` | 截圖工具 |
