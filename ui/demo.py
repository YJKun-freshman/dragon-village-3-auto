# -*- coding: utf-8 -*-
"""
介面展示：用假的任務和假的日誌跑起來，不需要遊戲。

    在 D:\\龍村3 執行：  py -3 -m ui.demo      （或雙擊 ui\\demo.bat）

出招流程的文字 ↔ 清單轉換直接讀 combat/sequence.py（只用到 re，不會載入遊戲相關模組）；
找不到時用這裡的簡易版。
"""
import importlib.util
import os
import random
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui import MainWindow  # noqa: E402


# ------------------------------------------------------------------ 出招流程工具
def load_sequence_tools():
    path = os.path.join(ROOT, "combat", "sequence.py")
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location("_demo_sequence", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {"parse": mod.parse, "to_text": mod.to_text, "validate": mod.validate}

    names = {"技能1": {"action": "skill1"}, "技能2": {"action": "skill2"}, "必殺技": {"action": "ult"},
             "普攻": {"action": "attack"}, "自動": {"action": "auto", "rounds": 0}}

    def parse(text):
        out = []
        for tok in [t.strip() for t in (text or "").split(">") if t.strip()]:
            if tok in names:
                out.append(dict(names[tok]))
            elif tok.startswith("替換"):
                out.append({"action": "swap", "slot": int(tok[2:])})
            elif tok.startswith("自動"):
                out.append({"action": "auto", "rounds": int(tok[2:])})
            elif tok.startswith("回到"):
                out.append({"action": "goto", "step": int(tok[2:])})
            else:
                raise ValueError(f"「{tok}」看不懂")
        return validate(out)

    def validate(steps):
        if not steps:
            raise ValueError("出招流程是空的")
        return steps

    def to_text(steps):
        def one(s):
            a = s["action"]
            return {"swap": f"替換{s.get('slot')}", "goto": f"回到{s.get('step')}",
                    "auto": f"自動{s['rounds']}" if s.get("rounds") else "自動"}.get(
                a, {"skill1": "技能1", "skill2": "技能2", "ult": "必殺技", "attack": "普攻"}.get(a, a))
        return " > ".join(one(s) for s in steps)

    return {"parse": parse, "to_text": to_text, "validate": validate}


# ------------------------------------------------------------------ 假任務
def raid_params(default_seq):
    stay, mini = "留在畫面等打完", "最小化後結束腳本"
    return [
        dict(key="sequence", label="出招流程", type=str, default=default_seq, widget="sequence",
             help="用 > 分隔，例：技能1 > 替換2 > 必殺技 > 自動"),
        dict(key="enter", label="從入口自動進場", type=bool, default=True,
             help="停在討伐戰入口或隊伍確認畫面時，自動按「戰鬥準備」→「戰鬥」（會用掉體力）"),
        dict(key="refill_ad", label="體力不足時看廣告", type=bool, default=False,
             help="補體力的順序：看廣告 → 活力恢復劑 → 鑽石"),
        dict(key="refill_potion", label="體力不足時用活力恢復劑", type=bool, default=False, help="一次用 1 瓶（+60）"),
        dict(key="refill_gems", label="體力不足時用鑽石", type=bool, default=False),
        dict(key="confirm", label="打完按確認", type=bool, default=True),
        dict(key="finish_mode", label="最後的自動", type=str, default=stay, choices=[stay, mini],
             help=f"{stay}：腳本看到打完、按確認才停\n{mini}：讓遊戲在背景打，腳本直接結束"),
        dict(key="turn_timeout", label="等出招最多(秒)", type=float, default=90.0, min=10, max=600,
             help="超過這個時間都沒輪到我方出招，就當作卡住並停止"),
        dict(key="battle_timeout", label="整場最多(秒)", type=float, default=900.0, min=60, max=3600),
    ]


FISHING = [
    dict(key="max_rounds", label="釣魚次數上限", type=int, default=100, min=1, max=9999,
         help="魚餌一次最多 20 個；沒開「自動看廣告」時用完就停止"),
    dict(key="watch_ads", label="魚餌用完時自動看廣告", type=bool, default=False,
         help="遊戲視窗請調成 9:16（直的），廣告的略過鍵才會在畫面裡"),
    dict(key="max_ads", label="最多看幾次廣告", type=int, default=5, min=1, max=50),
    dict(key="react_delay", label="上鉤後延遲點擊(秒)", type=float, default=0.0, min=0.0, max=1.0,
         help="「！」只出現約 0.3 秒，建議 0"),
    dict(key="click_interval", label="連點間隔(秒)", type=float, default=0.06, min=0.02, max=0.5,
         help="拉魚時每次點擊的間隔，越小點越快"),
    dict(key="cast_delay", label="每輪間隔(秒)", type=float, default=5.0, min=0.0, max=60.0,
         help="回到主畫面後等多久再拋竿"),
    dict(key="bite_timeout", label="等待咬鉤最長(秒)", type=float, default=60.0, min=5.0, max=600.0),
]


def fill(params):
    for p in params:
        for k in ("min", "max", "choices", "help", "widget"):
            p.setdefault(k, None if k != "help" else "")
    return params


def guild_params(default_seq="技能1 > 自動"):
    return [p for p in raid_params(default_seq) if not p["key"].startswith("refill_") and p["key"] != "finish_mode"] + [
        dict(key="mode", label="模式", type=str, default="挑戰", choices=["挑戰", "練習"],
             help="挑戰：一天一次；練習：不限次數")]


RAID_DESC = "自動進入討伐戰，照出招流程打完一場。"
GUILD_DESC = "從公會戰役畫面開始，自動按「挑戰」或「練習」打完一場。"
GROUPS = [{"path": ("戰鬥", "討伐戰"), "id": "raid", "name": "討伐戰"},
          {"path": ("戰鬥", "公會BOSS"), "id": "guild_boss", "name": "公會BOSS"}]


def make_custom(group, name, values=None):
    raid = group[-1] == "討伐戰"
    params = fill(raid_params("技能1 > 自動") if raid else guild_params())
    for p in params:
        if values and p["key"] in values:
            p["default"] = values[p["key"]]
        if raid and p["key"] in ("refill_ad", "refill_potion"):
            p["default"] = True if not (values and p["key"] in values) else p["default"]
    return {"path": tuple(group) + (name,), "description": RAID_DESC if raid else GUILD_DESC,
            "params": params, "editable": True, "group": tuple(group)}


class FakeEditor:
    """假的 task_editor（照 02「自訂戰鬥項目」）：自訂項目放在記憶體裡。"""

    def __init__(self):
        self.items = {GROUPS[0]["path"]: [("瑪歛克", {"sequence": "技能1 > 自動"}),
                                         ("泰迪布羅", {"sequence": "技能1 > 替換2 > 必殺技 > 替換3 > 必殺技 > 自動"})],
                      GROUPS[1]["path"]: []}
        self.running = lambda: False

    def tasks(self):
        out = []
        for g in GROUPS:
            out += [make_custom(g["path"], n, v) for n, v in self.items[g["path"]]]
        return out + FIXED

    def _check(self, group, name, keep=None):
        from ui.dialogs import validate_name
        n, err = validate_name(name, [x for x, _ in self.items[tuple(group)]], keep=keep)
        return n, err

    def add(self, group, name, values):
        if self.running():
            return False, "執行中不能編輯", None
        n, err = self._check(group, name)
        if err:
            return False, err, None
        self.items[tuple(group)].append((n, dict(values or {})))
        return True, f"已新增「{n}」", self.tasks()

    def rename(self, path, new):
        g = tuple(path[:-1])
        n, err = self._check(g, new, keep=path[-1])
        if err:
            return False, err, None
        self.items[g] = [(n if x == path[-1] else x, v) for x, v in self.items[g]]
        return True, f"已改名為「{n}」", self.tasks()

    def delete(self, path):
        g = tuple(path[:-1])
        self.items[g] = [(x, v) for x, v in self.items[g] if x != path[-1]]
        return True, f"已刪除「{path[-1]}」", self.tasks()

    def move(self, path, delta):
        g = tuple(path[:-1])
        lst = self.items[g]
        i = next(k for k, (x, _) in enumerate(lst) if x == path[-1])
        j = i + delta
        if not 0 <= j < len(lst):
            return False, "已經在最上面了" if delta < 0 else "已經在最下面了", None
        lst[i], lst[j] = lst[j], lst[i]
        return True, "", self.tasks()

    def as_dict(self):
        return {"add": self.add, "rename": self.rename, "delete": self.delete, "move": self.move}


FIXED = [
    {"path": ("釣魚",), "description": "自動釣魚。開始前請先進入釣魚畫面（廣場 → 釣魚）。",
     "params": fill(FISHING)},
    {"path": ("開發測試", "背景點擊"), "description": "（展示用）每隔一段時間點一下指定位置。",
     "params": fill([dict(key="count", label="次數", type=int, default=5, min=1, max=100),
                     dict(key="interval", label="間隔(秒)", type=float, default=1.0, min=0.1, max=10.0)])},
    {"path": ("開發測試", "沒有參數的任務"), "description": "（展示用）沒有任何參數。", "params": []},
]
TASKS = FixedTasks = None      # 舊名稱（測試腳本用）：見 main() 裡的 editor.tasks()


# ------------------------------------------------------------------ 假的執行
class FakeRunner:
    def __init__(self):
        self.ui = None
        self.stop_event = threading.Event()

    def start(self, path, values):
        self.stop_event = threading.Event()
        self.ui.append_log(f"開始任務：{' / '.join(path)}")
        self.ui.append_log(f"參數：{values}")
        threading.Thread(target=self._run, args=(path, values), daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def _run(self, path, values):
        ui = self.ui
        ui.set_running(True)
        total = 12
        for i in range(1, total + 1):
            if self.stop_event.wait(1.0):
                ui.append_log("已停止", "warn")
                break
            ui.set_progress(f"第 {i}/{total} 輪")
            r = random.random()
            if r < 0.12:
                ui.append_log(f"第 {i} 輪：畫面載入比較久，再等一下", "warn")
            elif r < 0.2:
                ui.append_log(f"第 {i} 輪：找不到按鈕，3 秒後重試（這是假的錯誤）", "error")
            else:
                ui.append_log(f"第 {i} 輪：完成一個動作，這一行故意寫長一點，看看視窗變窄時日誌會不會正確換行並對齊時間後面")
        else:
            ui.append_log("任務完成")
        ui.set_running(False)


class FakeSettings:
    """假的設定選單回呼（照 02「設定選單（定案）」）。F12 假裝被別的程式佔用。"""

    def __init__(self, runner):
        self.runner = runner
        self.keys = {"start": "F5", "stop": "F6"}
        self.windows = [{"id": 101, "title": "龍村3 - 小魚乾"}, {"id": 202, "title": "龍村3 - 小魚乾的分身"}]
        self.current = 101

    def as_dict(self):
        return {"hotkeys": dict(self.keys), "default_hotkeys": {"start": "F5", "stop": "F6"},
                "set_hotkeys": self.set_hotkeys, "pause_hotkeys": self.pause,
                "list_windows": lambda: list(self.windows), "current_window": lambda: self.current,
                "select_window": self.select}

    def set_hotkeys(self, start, stop):
        from ui.settings_dialog import normalize
        for name, k in (("開始", start), ("停止", stop)):
            norm, err = normalize(k)
            if err:
                return False, f"{name}熱鍵：{err}"
            if norm == "F12":
                return False, f"{name}熱鍵：F12 已經被其他程式使用（展示用的假錯誤）"
        self.keys = {"start": start, "stop": stop}
        self.runner.ui.set_hotkey_labels(start, stop)
        self.runner.ui.append_log(f"（展示）熱鍵改成 開始 {start}、停止 {stop}")
        return True, ""

    def pause(self, paused):
        self.runner.ui.append_log("（展示）暫停全域熱鍵" if paused else "（展示）恢復全域熱鍵")
        return True, ""

    def select(self, wid):
        self.current = wid
        name = next(w["title"] for w in self.windows if w["id"] == wid)
        self.runner.ui.set_game_status(f"已連接（{name.split(' - ')[-1]}）", True)
        return True, ""


def main():
    runner = FakeRunner()
    fake_settings = FakeSettings(runner)
    editor = FakeEditor()
    win = MainWindow(
        title="龍村3 自動腳本 v0.1.0",
        tasks=editor.tasks(),
        task_groups=GROUPS,
        task_editor=editor.as_dict(),
        on_start=runner.start,
        on_stop=runner.stop,
        saved_values={("釣魚",): {"max_rounds": 50}},
        selected=("戰鬥", "討伐戰", "泰迪布羅"),
        sequence_tools=load_sequence_tools(),
        on_open_logs=lambda: runner.ui.append_log("（展示）這裡會開啟日誌資料夾"),
        settings=fake_settings.as_dict(),
    )
    runner.ui = win
    editor.running = lambda: win.running
    win.set_game_status("已連接（562×1001）", True)
    win.append_log("這是展示模式：任務和日誌都是假的，不會操作遊戲")
    win.append_log("試試看：切換任務、改參數、編輯出招流程、按開始（F5）／停止（F6）、精簡模式、⚙ 設定")
    win.append_log("這是一行警告的樣子", "warn")
    win.append_log("這是一行錯誤的樣子", "error")

    def flaky_game():
        time.sleep(20)
        win.set_game_status("找不到視窗", False)
        time.sleep(5)
        win.set_game_status("已連接（562×1001）", True)

    threading.Thread(target=flaky_game, daemon=True).start()
    win.run()


if __name__ == "__main__":
    main()
