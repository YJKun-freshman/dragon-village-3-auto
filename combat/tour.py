# -*- coding: utf-8 -*-
"""
討伐戰巡迴：自動挑要打的王（04 待辦 1，2026-11-08 和使用者確認）

    村莊 → 羅盤 → 探險 →「討伐戰」→ 清單「參與前」→ 由上往下找第一張「有同名項目」的王
      → 點卡片 → 用那個項目的出招流程打一場（一律留在畫面等打完、按確認）→ 回清單 → 下一隻
      →「參與前」沒有任何有設定的王 → 結束

- 認王：卡片上的王名字，樣板放在 combat/templates/bosses/<名字>.png（名字＝項目名稱＝遊戲裡的寫法）
- 新的王：用截圖工具在清單上**只框王的名字文字**（不要包含屬性圖示、懸賞標記）→ 存到
  combat/templates/bosses/<名字>.png → 在「討伐戰」新增同名項目，就會打（不用改程式）
- 補體力用巡迴自己的設定；項目的「最後的自動」在巡迴裡一律當「留在畫面等打完」（使用者決定）
- 探險的討伐戰卡片顯示「委託戰鬥中！」（之前最小化的戰鬥還沒打完）→ 等；3 分鐘沒變 → 右下 X → 羅盤 → 探險 重新整理
"""
import os
import time

from core import paths
from core.task import Param, Task, TaskStopped

from .battle import Screen
from .kinds import Raid, make_item
from .raid.common import STAY

BOSS_DIR = "combat/templates/bosses/"
R_NAMES = (0.05, 0.18, 0.80, 0.65)     # 清單上王名字的範圍（「練習戰鬥」卡片在下面，不找）
NAME_THR = 0.88                        # 名字樣板門檻（同一個名字 0.97～1.00；別隻王最高 0.79）
CARD_DX = 0.30                         # 點卡片：名字往右 30%、往下 4%（避開右上的垃圾桶、下面的技能圖示）
CARD_DY = 0.04
TAB_BEFORE = (0.35, 0.17)              # 「參與前」分頁
BUSY_REFRESH = 180                     # 「委託戰鬥中」超過這麼多秒就重新整理


class RaidTour(Task):
    path = ("戰鬥", "討伐戰巡迴")
    description = ("討伐戰巡迴：從村莊走到討伐戰清單，「參與前」的王有同名項目的就用那個項目的流程打一場，"
                   "打完回清單繼續，直到沒有可以打的。")
    needs_items = "raid"
    params = [
        Param("max_battles", "最多打幾場", int, default=10, min=1, max=50),
        Param("refill_ad", "體力不足時看廣告", bool, default=True,
              help="補體力的順序：看廣告 → 活力恢復劑 → 鑽石（巡迴用這裡的設定，不看各項目的）"),
        Param("refill_potion", "體力不足時用活力恢復劑", bool, default=True, help="一次用 1 瓶（+60）"),
        Param("refill_gems", "體力不足時用鑽石", bool, default=False, help="一次 50 鑽石（+60）"),
        Param("nav_timeout", "走到清單最多(秒)", float, default=60, min=20, max=600),
    ]

    # ------------------------------------------------------------ 主流程
    def run(self):
        names = [n for n in (self.items or {}) if self._has_template(n)]
        missing = [n for n in (self.items or {}) if not self._has_template(n)]
        if missing:
            self.log(f"⚠ 這些項目沒有名字樣板，巡迴會認不出來：{'、'.join(missing)}"
                     f"（用截圖工具在討伐戰清單上只框王的名字，存到 {BOSS_DIR}<名字>.png）")
        if not names:
            self.log("❌ 沒有任何可以認的王（討伐戰項目要有同名的名字樣板），已停止")
            return
        self.log(f"開始討伐戰巡迴：認得 {'、'.join(names)}")
        fails = {}
        done = 0
        while done < self.values["max_battles"]:
            self.check_stop()
            self.set_progress(f"討伐戰巡迴：已打 {done} 場")
            if not self._goto_list():
                return
            self.wait(1.0)
            s = Screen(self.game)
            pick = self._pick(s, names, fails)
            if pick is None:
                self.log(f"✅ 「參與前」沒有可以打的王了，巡迴結束（共打 {done} 場）")
                self.set_progress(f"討伐戰巡迴：完成 {done} 場")
                return
            name, m = pick
            self.log(f"▶ 第 {done + 1} 場：{name}")
            self.game.click(min(0.95, m.x + CARD_DX), m.y + CARD_DY)
            result = self._fight(name)
            if result == "done":
                done += 1
            elif result == "no_stamina":
                self.log("❌ 體力不足，巡迴結束")
                return
            else:
                fails[name] = fails.get(name, 0) + 1
                self.log(f"⚠ {name} 這場沒打成（{fails[name]} 次），回清單繼續")
        self.log(f"✅ 已打滿 {done} 場（最多打幾場），巡迴結束")

    # ------------------------------------------------------------ 一場
    def _fight(self, name):
        values = dict(self.items[name])
        values["finish_mode"] = STAY                 # 巡迴裡一律留在畫面等打完
        values["confirm"] = True
        values["enter"] = True
        for k in ("refill_ad", "refill_potion", "refill_gems"):
            values[k] = self.values[k]
        task = make_item(Raid, name)(self.game, values, self._log, stop_event=self.stop_event,
                                     progress=self._progress)
        task.run()
        return getattr(task, "result", "failed")

    # ------------------------------------------------------------ 清單
    def _has_template(self, name):
        return os.path.exists(paths.resource(BOSS_DIR + name + ".png"))

    def _pick(self, s, names, fails):
        """清單上由上往下第一張有設定、還沒失敗 2 次的王。"""
        found = []
        for n in names:
            if fails.get(n, 0) >= 2:
                continue
            m = s.game.find(BOSS_DIR + n + ".png", region=R_NAMES, threshold=NAME_THR, frame=s.frame,
                            scales=(1.0, 1.08, 1.16, 1.26, 0.93), blur=5)
            if m:
                found.append((m.y, n, m))
        if not found:
            return None
        found.sort(key=lambda t: t[0])
        return found[0][1], found[0][2]

    def _goto_list(self):
        """走到討伐戰清單的「參與前」分頁。回傳 False = 走不到（已寫日誌）。"""
        end = time.monotonic() + self.values["nav_timeout"]
        last = {}
        busy_since = None

        def act(key, text, fn, gap=3):
            if time.monotonic() - last.get(key, 0) < gap:
                return
            self.log(text)
            fn()
            last[key] = time.monotonic()

        while time.monotonic() < end:
            self.check_stop()
            s = Screen(self.game)
            if s.find("raid_list"):
                return True
            if s.ended:                                       # 上一場的結算還在
                m = s.find("confirm")
                if m:
                    act("confirm", "按「確認」", lambda: self.game.click_match(m))
            elif s.find("raid_title") and not (s.find("start") or s.find("start_practice") or s.find("prepare")):
                act("tab", "切到「參與前」", lambda: self.game.click(*TAB_BEFORE))
            elif s.find("explore_busy"):
                busy_since = busy_since or time.monotonic()
                end = max(end, time.monotonic() + 30)
                waited = time.monotonic() - busy_since
                self.set_progress(f"討伐戰巡迴：等委託戰鬥打完（{waited:.0f} 秒）")
                if waited > BUSY_REFRESH:
                    busy_since = time.monotonic()
                    m = s.find("close_br")
                    act("refresh", "「委託戰鬥中」太久了，關掉探險重新進來",
                        lambda: self.game.click_match(m) if m else self.game.click(0.92, 0.95))
            elif s.find("explore_raid"):
                busy_since = None
                m = s.find("explore_raid")
                act("explore", "按「討伐戰」", lambda: self.game.click(m.x, m.y))
            elif s.find("compass_go"):
                m = s.find("compass_go")
                act("go", "按「探險」", lambda: self.game.click(m.x, m.y))
            elif s.find("compass"):
                m = s.find("compass")
                act("compass", "按羅盤", lambda: self.game.click(m.x, m.y))
            elif s.find("prepare") or s.find("start") or s.find("start_practice"):
                m = s.find("close_br")                        # 王的入口／隊伍確認 → 按右下 X 回上一頁
                act("back", "按右下 X 回清單", lambda: self.game.click_match(m) if m else self.game.click(0.92, 0.95))
            self.wait(0.5)
        self._debug("走不到討伐戰清單")
        self.log(f"❌ {self.values['nav_timeout']:.0f} 秒內走不到討伐戰清單（目前：{Screen(self.game).name()}），"
                 "已停止。截圖存在 logs 資料夾。")
        return False

    # ------------------------------------------------------------ 工具
    def wait(self, sec):
        if not self.sleep(sec):
            raise TaskStopped()

    def _debug(self, reason):
        try:
            name = time.strftime("%m%d_%H%M%S") + f"_戰鬥_{reason}.png"
            self.game.save_frame(paths.data(os.path.join("logs", name)), self.game.last_frame)
        except Exception:
            pass
