# combat — 戰鬥

## 結構

| 檔案 | 內容 |
|---|---|
| `sequence.py` | 出招流程：文字 ↔ 步驟清單、檢查 |
| `battle.py` | 戰鬥畫面判斷（`Screen`）：我方回合、技能亮暗、AUTO、替換視窗、戰鬥結束、剩餘回合 |
| `kinds.py` | 戰鬥類型 `TEMPLATES = [Raid, GuildBoss]`、`make_item()` |
| `raid/common.py` | `BattleTask`：共用流程（進場 → 照流程打 → 結束 → 確認／最小化） |
| `templates/common/` | 共用樣板 |

## 戰鬥怎麼算結束

| 看到的畫面 | 判斷 |
|---|---|
| 「戰鬥結束」結算 | 打完 → 按確認（正式） |
| 自動中回到隊伍確認／討伐戰入口（連續 2 次） | 打完（練習模式沒有結算畫面） |
| 村莊下方「正在與團隊首領交戰中」 | 戰鬥被最小化到背景，遊戲自己會打完（變成委任）→ 腳本結束 |

- 最小化按鈕只有正式模式有（練習、公會 BOSS 沒有）
- 背景打完後，那排字會換成下一個委任（例：「火山(困難) 攻略中」），點開是委任日誌，有「討伐戰委任完成。記錄 N 分」

## 類型與項目（v0.4.0 起）

```text
戰鬥
├── 討伐戰（Raid，template_id="raid"）        ← 類型：戰鬥對話提供
│   ├── 瑪歛克                                 ← 項目：使用者在介面上新增／改名／複製／刪除
│   └── 泰迪布羅
└── 公會BOSS（GuildBoss，template_id="guild_boss"）
```

- 新王不用改程式，使用者自己新增項目
- 新**類型**：在 `kinds.py` 加一個 `BattleTask` 子類別（`template_id`、`group`、`type_name`、`uses_stamina`、`can_minimize`、`params = 類別.make_params(...)`、`default_items`），放進 `TEMPLATES`
- 項目的任務類別：`make_item(範本, 名稱, values)`；名稱在 `self.path[-1]`

## 參數

公會BOSS（遊戲裡叫「公會戰役」）：一天挑戰一次、練習不限；從公會戰役畫面、隊伍確認或戰鬥中開始。
參數多一個 `mode`「模式」（挑戰／練習），沒有 `refill_*`、`finish_mode`。

討伐戰的參數：

| key | 標籤 | 類型 | 預設 |
|---|---|---|---|
| `sequence` | 出招流程 | str（`widget="sequence"`） | 項目自己的（見 `default_items`），新項目 `技能1 > 自動` |
| `enter` | 從入口自動進場 | bool | True |
| `refill_ad` | 體力不足時看廣告 | bool | True |
| `refill_potion` | 體力不足時用活力恢復劑 | bool | True |
| `refill_gems` | 體力不足時用鑽石 | bool | False |
| `confirm` | 打完按確認 | bool | True |
| `finish_mode` | 最後的自動 | choices：留在畫面等打完／最小化後結束腳本 | 留在畫面等打完 |
| `turn_timeout` | 等出招最多(秒) | float | 90 |
| `battle_timeout` | 整場最多(秒) | float | 900 |

## 給「Tkinter外型」的需求：出招流程編輯器（之後做，現在先用文字欄位）

目前 `sequence` 是普通的 `str` 參數，臨時介面顯示成文字欄位就能用，**不需要改介面約定**。
之後想要做成編輯器時，建議做法（到時候要照 00 第 6 節記錄介面變動）：

- `Param` 加一個標記，例：`Param("sequence", "出招流程", str, ..., widget="sequence")`，ui 看到就顯示編輯器，值仍然是**文字**（存設定檔、傳給任務都不變）
- 編輯器長相：
  ```
  流程：[泰迪布羅 高分 ▼] [新增] [複製] [改名] [刪除]     ← 已存流程（之後再做）
   1. 技能1
   2. 替換 → 第 2 隻
   3. 自動
            [↑] [↓] [刪除]
  加入：[技能1] [技能2] [必殺技] [普攻] [替換▼2/3] [自動] [自動N回合] [回到第N步]
  ```
- 文字 ↔ 清單互轉、檢查都用 `combat.sequence`（`parse` / `to_text` / `validate`、錯誤訊息是中文）。
  ui 不能 import combat 的話，由 app 把這三個函式當回呼傳給 ui

## 討伐戰巡迴（v0.5.0）

功能樹「戰鬥 / 討伐戰巡迴」：從村莊走到討伐戰清單，「參與前」的王有同名項目的，就用那個項目的出招流程打一場，直到沒有可以打的。

**新的王要怎麼加**
1. 在遊戲打開討伐戰清單（參與前）
2. 用截圖工具框出**王的名字文字**（例「提阿瑪特」）：不要框到左邊的屬性圖示（🔥／💧），也不要框到紅色「懸賞」標記
3. 存成 `combat/templates/bosses/<名字>.png`（截圖工具的資料夾填 `combat\templates\bosses`）
4. 在功能樹「討伐戰」底下新增**同名**項目、設定出招流程

名字要和遊戲裡一模一樣（例：遊戲寫「提阿瑪特」）。
