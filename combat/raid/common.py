# -*- coding: utf-8 -*-
"""
討伐戰共用流程：

    （討伐戰入口 →「戰鬥準備」→ 隊伍確認 →「戰鬥」）→ 照出招流程打 → 戰鬥結束 → 確認 → 停止

戰鬥類型（討伐戰、公會BOSS…）在 `combat/kinds.py` 繼承 BattleTask；
項目（瑪歛克、泰迪布羅…）由使用者在介面上建立，主程式動態產生子類別並設定 path。
"""
import os
import time

from core import paths
from core.task import Task, Param, TaskStopped

from ..battle import BTN, POTION_USE, REFILL_CARD, SWAP_SLOT_CLICK, Screen, round_changed
from ..sequence import TURN_ACTIONS, SequenceError, parse, step_text, to_text

MAX_RETRY = 3          # 寶珠不夠時最多補放幾次
POLL = 0.25            # 檢查畫面的間隔（秒）
MIN_ROUND_GAP = 4.0    # 「自動N」數回合：兩次回合變化至少隔幾秒（實測一回合 6～18 秒；22:25 有 1 秒內數兩次的誤判）
CONFIRM_SETTLE = 2.0   # 「確認」出現後等幾秒才按（實測剛出現時按會沒反應）

SEQ_HELP = ("用 > 分隔，例：技能1 > 替換2 > 必殺技 > 自動\n"
            "可用：技能1、技能2、必殺技、普攻、替換1～3（換成隊伍第幾隻）、\n"
            "自動（打到結束）、自動5（自動 5 回合後切回手動）、回到3（跳回第 3 步）")


STAY = "留在畫面等打完"
MINIMIZE = "最小化後結束腳本"


class BattleEnded(Exception):
    """戰鬥途中看到「戰鬥結束」，或練習模式打完直接回到隊伍確認／入口。"""


class Deviated(Exception):
    """角色倒下被迫換人，已經不是原本預期的順序 → 剩下的交給自動。"""


class Minimized(Exception):
    """戰鬥被縮到背景（村莊出現「正在與團隊首領交戰中」）。"""


class BattleTask(Task):
    """回合制戰鬥的共用流程。類型（kinds.py）設定下面幾個屬性，項目名稱在 path 的最後一段。"""
    type_name = "戰鬥"            # 類型名稱（日誌用），例：討伐戰
    uses_stamina = True           # 會不會遇到體力不足（有沒有 refill_* 參數）
    can_minimize = True           # 戰鬥畫面有沒有最小化按鈕（有沒有 finish_mode 參數）

    @property
    def boss(self):
        """項目名稱（使用者取的，例：瑪歛克）。"""
        return self.path[-1] if self.path else self.type_name

    @classmethod
    def make_params(cls, default_sequence="技能1 > 自動", refill=None):
        """
        refill：None = 沒有補體力參數；(廣告, 恢復劑, 鑽石) = 三個勾選的預設值
        """
        ps = [
            Param("sequence", "出招流程", str, default=default_sequence, help=SEQ_HELP, widget="sequence"),
            Param("enter", "從入口自動進場", bool, default=True,
                  help="停在入口或隊伍確認畫面時，自動按「戰鬥準備」→「戰鬥」"),
        ]
        if refill is not None:
            ad, potion, gems = refill
            ps += [
                Param("refill_ad", "體力不足時看廣告", bool, default=ad,
                      help="補體力的順序：看廣告 → 活力恢復劑 → 鑽石（只用有勾的、今天還能用的）\n"
                           "遊戲視窗建議 9:16，廣告的略過鍵才會在畫面裡"),
                Param("refill_potion", "體力不足時用活力恢復劑", bool, default=potion, help="一次用 1 瓶（+60）"),
                Param("refill_gems", "體力不足時用鑽石", bool, default=gems, help="一次 50 鑽石（+60），每天有次數限制"),
            ]
        ps.append(Param("confirm", "打完按確認", bool, default=True, help="戰鬥結束後按「確認」"))
        if cls.can_minimize:
            ps.append(Param("finish_mode", "最後的自動", str, default=STAY, choices=[STAY, MINIMIZE],
                            help="流程跑到最後的「自動」之後：\n"
                                 f"{STAY}：腳本看到打完、按確認才停\n"
                                 f"{MINIMIZE}：按最小化讓遊戲在背景打，腳本直接結束（結果看遊戲裡的日誌）\n"
                                 "練習模式沒有最小化按鈕，會自動改成留在畫面"))
        ps += [
            Param("turn_timeout", "等出招最多(秒)", float, default=90, min=10, max=600,
                  help="超過這個時間都沒輪到我方出招，就當作卡住並停止"),
            Param("battle_timeout", "整場最多(秒)", float, default=900, min=60, max=3600),
        ]
        return ps

    def opt(self, key, default=False):
        """這個類型沒有的參數（例：公會BOSS 沒有 refill_*）回傳 default。"""
        return self.values.get(key, default)

    # ------------------------------------------------------------ 主流程
    def run(self):
        try:
            steps = parse(self.values["sequence"])
        except SequenceError as e:
            self.log(f"❌ 出招流程寫錯：{e}")
            return
        self.log(f"開始 {self.type_name}／{self.boss}：{to_text(steps)}")
        self.result = "failed"           # 給巡迴看：done（打完）／minimized／no_stamina／failed
        self.t0 = time.monotonic()
        self.turns = 0
        self.no_result = False           # 練習模式：打完沒有結算畫面
        self.manual_done = False         # 手動步驟都做完了
        try:
            if not self._enter():
                return
            try:
                self._play(steps)
            except Deviated:
                # 使用者決定：被迫換人後順序已經亂了，不再照流程，直接自動打到結束
                self.log("角色倒下、順序已經跟流程不一樣，剩下的改成自動打到結束")
                self._set_auto(True)
                self.manual_done = True
                self._auto_to_end()
        except BattleEnded:
            pass
        except Minimized:
            if self.manual_done:
                self.log("✅ 戰鬥已縮到背景，遊戲會自己打完（結果看遊戲裡的日誌），腳本結束")
            else:
                self.log("⚠ 手動步驟還沒做完，戰鬥就被縮到背景了，剩下的交給遊戲自動打。腳本結束")
            self.set_progress(f"{self.boss}：背景戰鬥中")
            self.result = "minimized"
            return
        self._finish()
        self.result = "done"

    # ------------------------------------------------------------ 進場
    def _enter(self):
        end = time.monotonic() + 30
        clicked = {}
        tried = set()                                     # 已經用過的補體力方式（每種最多一次）
        while time.monotonic() < end:
            s = self.screen()
            if s.ended:
                raise BattleEnded()
            if s.in_battle or s.swap_open:
                return True
            if s.find("no_gem"):
                m = s.find("no_gem_go")
                if m:
                    self.log("有龍尚未裝備寶珠的提示 → 按「繼續遊戲」")
                    self.game.click_match(m)
                    self.wait(1.5)
                    continue
            if s.find("no_stamina") or s.find("potion"):
                if self._refill(tried):
                    end = time.monotonic() + 30           # 補完重新計時，回到隊伍確認再按「戰鬥」
                    clicked = {}
                    continue
                self._stamina_stop()
                return False
            if s.find("bg_fighting"):
                self.log("❌ 首領戰正在背景進行（村莊顯示「正在與團隊首領交戰中」），請先點回戰鬥畫面再開始")
                return False
            extra = self._enter_extra(s, clicked)        # 類型自己的入口（例：公會戰役）
            if extra == "stop":
                return False
            if extra == "clicked":
                end = max(end, time.monotonic() + 15)     # 還在走路（村莊 → 選單 → 公會…）就延長等待
                self.wait(POLL)
                continue
            for key, label in (("start", "戰鬥"), ("start_practice", "戰鬥"), ("prepare", "戰鬥準備")):
                m = s.find(key)
                if not m:
                    continue
                if not self.values["enter"]:
                    self.log("❌ 目前在討伐戰入口，請先進入戰鬥再開始（或勾選「從入口自動進場」）")
                    return False
                if time.monotonic() - clicked.get(key, 0) > 3:
                    self.log(f"按「{label}」")
                    self.game.click_match(m)
                    clicked[key] = time.monotonic()
                break
            self.wait(POLL)
        self._debug("進不了戰鬥")
        self.log(f"❌ 30 秒內沒有進入戰鬥畫面（目前：{self.screen().name()}），已停止。截圖存在 logs 資料夾。")
        return False

    def _enter_extra(self, s, clicked):
        """類型自己的入口畫面。回傳 None（不是）、"clicked"（按了東西）、"stop"（要停止）。"""
        return None

    # ------------------------------------------------------------ 照流程打
    def _play(self, steps):
        s = self.screen()
        if steps[0]["action"] != "auto" and s.auto_on:
            self.log("AUTO 開著，先關掉")
            self._set_auto(False)

        i, retry, goto_count = 0, 0, 0
        while i < len(steps):
            self.check_stop()
            step = steps[i]
            a = step["action"]
            self.set_progress(f"{self.boss}：第 {i + 1}/{len(steps)} 步 {step_text(step)}")

            if a == "goto":
                goto_count += 1
                i = step["step"] - 1
                continue

            if a == "auto":
                self._set_auto(True)
                if not step.get("rounds"):
                    self.manual_done = True
                    self._auto_to_end()
                    return
                self._auto_rounds(step["rounds"])
                self._set_auto(False)
                i += 1
                continue

            # 出招
            s = self._wait_my_turn()
            if a == "swap":
                if self._swap(step["slot"]):
                    self._wait_turn_used()
                i += 1
                continue
            if not s.ready(a):
                if retry < MAX_RETRY:
                    retry += 1
                    self.log(f"「{step_text(step)}」現在不能用（寶珠不夠或冷卻中），這回合先普攻，下回合再補（第 {retry} 次）")
                    self._act("attack", s)
                    continue                     # 同一步再試
                self.log(f"⚠ 「{step_text(step)}」連續 {MAX_RETRY} 回合都不能用，跳過這一步")
                retry = 0
                i += 1
                continue
            retry = 0
            self.log(f"第 {i + 1} 步：{step_text(step)}")
            self._act(a, s)
            i += 1

        # 流程跑完還沒結束 → 交給自動
        self.log("流程跑完了，開自動打到結束")
        self._set_auto(True)
        self.manual_done = True
        self._auto_to_end()

    def _auto_to_end(self):
        """最後的自動：留在畫面等打完，或按最小化交給遊戲。"""
        if self.opt("finish_mode", STAY) == MINIMIZE:
            # 剛放完必殺技時動畫會蓋住按鈕列，馬上找會找不到（2026-11-08 20:49 誤判成練習）→ 最多等 8 秒
            t0 = time.monotonic()
            s = self._until(lambda s: s.find("minimize") or (s.in_battle and time.monotonic() - t0 > 4), 8)
            m = s.find("minimize") if s else None
            if m is None:
                self.log("看不到最小化按鈕（練習／公會BOSS 沒有這顆），改成留在畫面等打完")
            else:
                self.wait(1.0)                            # 剛開 AUTO 馬上按最小化，第一下常常沒反應（23:01 實測）
                m = self.screen().find("minimize") or m
                for attempt in range(3):
                    self.log("按最小化，交給遊戲在背景打")
                    self.game.click_match(m)
                    self._until(lambda s: False, 3)     # 看到「交戰中」會丟 Minimized
                    m = self.screen().find("minimize")
                    if m is None:
                        break
                self.log("⚠ 按了最小化但沒回到村莊，改成留在畫面等打完")
        self.log("自動戰鬥，等戰鬥結束")
        self._wait_end()

    REFILL_NAMES = {"ad": "看廣告", "potion": "活力恢復劑", "gems": "鑽石"}

    def _refill(self, tried):
        """體力不足：照「廣告 → 恢復劑 → 鑽石」的順序，用第一個有勾、今天還能用的。True = 有補。"""
        s = self.screen()
        if s.find("potion") and not s.find("no_stamina"):   # 停在恢復劑數量視窗 → 先關掉回到恢復活力
            self._close_popup()
            s = self.screen()
        for kind in ("ad", "potion", "gems"):
            if not self.opt("refill_" + kind) or kind in tried:
                continue
            tried.add(kind)
            name = self.REFILL_NAMES[kind]
            if not s.refill_ready(kind):
                self.log(f"體力不足：{name}今天已經用完了")
                continue
            self.log(f"體力不足 → 用{name}補體力")
            ok = {"ad": self._refill_ad, "potion": self._refill_potion, "gems": self._refill_gems}[kind]()
            if ok:
                self.log(f"✅ 已用{name}補體力，重新按「戰鬥」")
                self._close_popup()                       # 恢復活力視窗還開著就關掉
                self.wait(1.5)                            # 等視窗關閉動畫，太快按「戰鬥」會沒反應（23:01 實測）
                return True
            s = self.screen()
        return False

    def _close_popup(self):
        for attempt in range(3):
            s = self.screen()
            if not (s.find("no_stamina") or s.find("potion")):
                return
            m = s.find("popup_x")
            if m:
                self.game.click_match(m)
            self.wait(1.0)

    def _refill_potion(self):
        self.game.click(*REFILL_CARD["potion"])
        if not self._until_plain(lambda s: s.find("potion"), 4):
            self.log("⚠ 按了活力恢復劑，但數量視窗沒出現（可能沒有恢復劑了）")
            return False
        self.wait(0.5)
        self.game.click(*POTION_USE)                      # 數量預設 1 個
        if not self._until_plain(lambda s: not s.find("potion"), 4):
            self.log("⚠ 按了「使用」但視窗沒關")
            self._close_popup()
            return False
        return True

    def _refill_gems(self):
        self.game.click(*REFILL_CARD["gems"])
        self.wait(2.0)
        s = self.screen()
        if s.find("start") or s.find("start_practice") or s.find("no_stamina"):
            return True
        # 可能有確認視窗（還沒看過長什麼樣子）→ 不亂按，停下來讓使用者截圖
        self._debug("鑽石補體力後不認得的畫面")
        self.log("❌ 按了鑽石之後出現不認得的畫面（可能是確認視窗），已停止。"
                 "截圖存在 logs 資料夾，請傳給開發者新增樣板。")
        raise TaskStopped()

    def _refill_ad(self):
        """看廣告：按廣告卡 → 用 core 的 AdCloser 關廣告（core v0.5.0）→ 回到恢復活力或隊伍確認。"""
        from core.ads import AdCloser
        g = self.game
        g.click(*REFILL_CARD["ad"])
        if self._until_plain(lambda s: not s.find("no_stamina"), 5) is None:
            self.log("⚠ 按了看廣告，但沒有進入廣告")
            return False

        def back(frame):
            s = Screen(g, frame)
            return bool(s.find("no_stamina") or s.find("start") or s.find("start_practice"))

        t0 = time.monotonic()
        ads = AdCloser(g, log=self.log, debug_name="戰鬥")
        if ads.close_until(done=back, timeout=60, debug_on_timeout="廣告關不掉"):
            self.log(f"📺 廣告結束（{time.monotonic() - t0:.0f} 秒）")
            self.wait(1.0)
            return True
        self.check_stop()
        self.log("❌ 廣告關不掉，已停止。截圖存在 logs 資料夾。")
        raise TaskStopped()

    def _stamina_stop(self):
        """體力不足而且沒有（可用的）補體力方式：按 X 關掉視窗，然後停止。"""
        self.result = "no_stamina"
        self._close_popup()
        if any(self.opt("refill_" + k) for k in ("ad", "potion", "gems")):
            self.log("❌ 體力不足，勾選的補體力方式都不能用了，已關掉「恢復活力」視窗並停止")
        else:
            self.log("❌ 體力不足（正式討伐戰一場要 10 體力），已關掉「恢復活力」視窗並停止"
                     "（可以在參數勾選看廣告／活力恢復劑／鑽石自動補）")
        self.set_progress(f"{self.boss}：體力不足")

    # ------------------------------------------------------------ 動作
    def _act(self, action, s=None):
        """按技能／普攻，確認這回合有用掉（沒用掉就再按一次）。"""
        for attempt in range(3):
            self.game.click(*BTN[action])
            if attempt == 0:
                self.turns += 1
            if self._wait_turn_used(timeout=4, quiet=True):
                return
            self.log(f"按了「{action}」好像沒反應，再按一次")
        self._debug("按技能沒反應")
        self.log("❌ 按了 3 次都沒反應，已停止。截圖存在 logs 資料夾。")
        raise TaskStopped()

    def _swap(self, slot):
        """換成第 slot 隻。回傳 True = 有換（用掉回合）。"""
        for attempt in range(3):
            self.game.click(*BTN["swap"])
            if self._until(lambda s: s.swap_open, 4):
                break
        else:
            self._debug("替換視窗沒出現")
            self.log("❌ 按了替換，但換角色的視窗沒出現，已停止。截圖存在 logs 資料夾。")
            raise TaskStopped()
        self.wait(0.3)                                    # 等視窗動畫停
        state = self.screen().slot_state(slot)
        if state == "上場中":
            self.log(f"⚠ 第 {slot} 隻已經在場上，不用換，跳過這一步")
            self._close_swap()
            return False
        if state == "不能換":
            self.log(f"⚠ 第 {slot} 隻已經倒下，不能換，跳過這一步")
            self._close_swap()
            return False
        if state is None:
            self.log(f"⚠ 看不出第 {slot} 格的狀態，照樣點點看")
        self.log(f"替換 → 第 {slot} 隻")
        self.game.click(*SWAP_SLOT_CLICK[slot])
        self.turns += 1
        if not self._until(lambda s: not s.swap_open, 4):
            self.log("⚠ 點了角色但視窗沒關，關掉視窗，跳過這一步")
            self._close_swap()
            return False
        return True

    def _forced_swap(self, s):
        """角色倒下 →「請選擇要替換的龍」：選最上面還活著（紫色）的那隻。"""
        self.wait(0.5)                                     # 等視窗動畫停
        s = self.screen()
        if not s.forced_swap:
            return
        states = {n: s.slot_state(n) for n in (1, 2, 3)}
        alive = [n for n, st in states.items() if st == "可換"]
        if not alive:
            self._debug("角色倒下沒得換")
            self.log(f"❌ 有角色倒下，但看不出能換哪一隻（{states}），已停止。截圖存在 logs 資料夾。")
            raise TaskStopped()
        n = alive[0]
        self.log(f"⚠ 有角色倒下，換上第 {n} 隻")
        self.game.click(*SWAP_SLOT_CLICK[n])
        if self._until_plain(lambda s: not s.forced_swap, 4) is None:
            self._debug("角色倒下換不了")
            self.log("❌ 角色倒下的替換視窗關不掉，已停止。截圖存在 logs 資料夾。")
            raise TaskStopped()
        if not self.manual_done:
            raise Deviated()

    def _until_plain(self, cond, timeout):
        """跟 _until 一樣，但不處理特殊畫面（給 _forced_swap 用，避免繞回自己）。"""
        end = time.monotonic() + timeout
        while True:
            s = self.screen()
            if cond(s):
                return s
            if time.monotonic() >= end:
                return None
            self.wait(POLL)

    def _close_swap(self):
        m = self.screen().find("swap_x")
        if m:
            self.game.click_match(m)
            self._until(lambda s: not s.swap_open, 4)

    def _set_auto(self, on):
        """
        開／關 AUTO。按一下之後等它真的變了（最多 3 秒）才算，沒變才再按。
        （原本按完只等 0.8 秒就重看，畫面還沒變就又按一次 → 開關來回切，23:12 實測「沒辦法關閉 AUTO」）
        """
        want = "AUTO 已開啟" if on else "AUTO 已關閉"
        for attempt in range(3):
            s = self.screen()
            if s.ended:
                raise BattleEnded()
            if s.auto_on is on:
                self.log(want)
                return
            if s.auto_on is None:
                self.wait(0.8)
                continue
            self.game.click(*s.auto_pos())
            if self._until(lambda s: s.auto_on is on, 3):
                self.log(want)
                return
        self.log(f"⚠ 沒辦法{'開啟' if on else '關閉'} AUTO（目前：{self.screen().name()}）")

    # ------------------------------------------------------------ 等待
    def screen(self):
        return Screen(self.game)

    def wait(self, sec):
        if not self.sleep(sec):
            raise TaskStopped()
        if time.monotonic() - self.t0 > self.values["battle_timeout"]:
            self._debug("整場超時")
            self.log("❌ 超過整場最長時間，已停止。截圖存在 logs 資料夾。")
            raise TaskStopped()

    def _until(self, cond, timeout):
        """等到 cond(screen) 成立；看到戰鬥結束丟 BattleEnded。"""
        end = time.monotonic() + timeout
        while True:
            s = self.screen()
            if s.ended:
                raise BattleEnded()
            if not s.in_battle and s.find("bg_fighting"):
                raise Minimized()
            if s.forced_swap:
                self._forced_swap(s)
                end = max(end, time.monotonic() + 10)      # 換人的時間不算在等待裡
                continue
            if cond(s):
                return s
            if time.monotonic() >= end:
                return None
            self.wait(POLL)

    def _wait_my_turn(self):
        s = self._until(lambda s: s.my_turn, self.values["turn_timeout"])
        if s is None:
            now = self.screen()
            if now.auto_on:
                self.log("⚠ 等出招時發現 AUTO 開著，關掉")
                self._set_auto(False)
                s = self._until(lambda s: s.my_turn, self.values["turn_timeout"])
            if s is None:
                self._debug("等不到我方回合")
                self.log(f"❌ {self.values['turn_timeout']:.0f} 秒都沒輪到我方出招"
                         f"（目前：{self.screen().name()}），已停止。截圖存在 logs 資料夾。")
                raise TaskStopped()
        self.wait(0.2)                       # 按鈕亮起的動畫
        s2 = self.screen()
        return s2 if s2.my_turn else s

    def _wait_turn_used(self, timeout=6, quiet=False):
        """出招後，等「請選擇…」消失（代表這回合已經送出）。"""
        ok = self._until(lambda s: not s.my_turn, timeout) is not None
        if not ok and not quiet:
            self.log("⚠ 出招後畫面好像沒變")
        return ok

    def _auto_rounds(self, n):
        """開著自動，數剩餘回合數字變了 n 次。"""
        self.log(f"自動 {n} 回合")
        last = self.screen().round_mask()
        count, pending, pend_n = 0, None, 0
        last_t = time.monotonic()      # 剛開自動 4 秒內的變化是上一個（手動）回合結束，不算（09:28 實測 1 秒就數了 1）
        end = time.monotonic() + self.values["turn_timeout"] * (n + 1)
        while count < n:
            if time.monotonic() > end:
                self.log(f"⚠ 數回合超時（數到 {count}/{n}），直接切回手動")
                return
            self.wait(0.3)
            s = self.screen()
            if s.ended:
                raise BattleEnded()
            if s.forced_swap:
                self._forced_swap(s)
                continue
            if not s.in_battle:
                continue
            m = s.round_mask()
            if not round_changed(last, m):
                pending, pend_n = None, 0
                continue
            # 連續兩次都一樣才算（避免特效閃過）
            if pending is not None and not round_changed(pending, m):
                pend_n += 1
            else:
                pending, pend_n = m, 1
            if pend_n >= 2 and time.monotonic() - last_t < MIN_ROUND_GAP:
                last, pending, pend_n = m, None, 0         # 太快了：當作特效，只更新基準
                continue
            if pend_n >= 2:
                last_t = time.monotonic()
                count += 1
                last, pending, pend_n = m, None, 0
                self.log(f"  經過 {count}/{n} 回合")
                self.set_progress(f"{self.boss}：自動中 {count}/{n} 回合")

    def _wait_end(self):
        outside = 0
        while True:
            self.wait(1.0)
            s = self.screen()
            if s.ended:
                raise BattleEnded()
            if not s.in_battle and s.find("bg_fighting"):
                raise Minimized()
            if s.forced_swap:
                self._forced_swap(s)
                continue
            if s.in_battle and s.auto_on is False:       # 被人手動關掉
                self.game.click(*s.auto_pos())
            # 練習模式打完沒有結算畫面，直接回到隊伍確認／入口（連續 2 次才算，避免轉場誤判）
            outside = outside + 1 if (not s.in_battle and s.outside) else 0
            if outside >= 2:
                self.no_result = True
                self.log(f"回到{s.name()}（練習模式打完沒有結算畫面）")
                raise BattleEnded()

    # ------------------------------------------------------------ 結束
    def _finish(self):
        used = time.monotonic() - self.t0
        self.log(f"✅ {self.boss} 戰鬥結束（約 {used:.0f} 秒，腳本出招 {self.turns} 次）")
        if self.values["confirm"] and not self.no_result:
            # 結算動畫跑完「確認」才會出現；每次按都記到日誌，方便查時間
            end = time.monotonic() + 30
            clicks = 0
            seen = None                                   # 「確認」第一次出現的時間
            while time.monotonic() < end and clicks < 5:
                t = time.monotonic()
                m = self.screen().find("confirm")
                if m is None:
                    if clicks:
                        break                             # 按過、確認不見了 = 成功
                    seen = None
                    self.wait(0.5)
                    continue
                if seen is None:
                    seen = t
                if clicks == 0 and t - seen < CONFIRM_SETTLE:
                    self.wait(0.3)                        # 剛出現時按了沒反應（結算動畫還在跑），等它停穩
                    continue
                clicks += 1
                self.game.click_match(m)
                self.log(f"按「確認」（第 {clicks} 次，找圖 {(time.monotonic() - t) * 1000:.0f} ms）")
                self.wait(1.5)
            if clicks == 0:
                self.log("⚠ 30 秒內沒看到「確認」，請自己按")
            elif self.screen().find("confirm"):
                self._debug("確認按不掉")
                self.log("⚠ 按了 5 次「確認」還在，請自己按。截圖存在 logs 資料夾。")
            else:
                s2 = self.screen()
                for _ in range(10):                       # 等回到戰鬥外的畫面（討伐戰清單／入口…，最多約 5 秒）
                    if s2.outside:
                        break
                    self.wait(0.5)
                    s2 = self.screen()
                self.log(f"已按確認（目前：{s2.name()}）")
                if not s2.outside:
                    self._debug("確認後的畫面")              # 還沒看過的畫面，存起來之後補判斷
        self.set_progress(f"{self.boss}：完成")

    def _debug(self, reason):
        try:
            name = time.strftime("%m%d_%H%M%S") + f"_戰鬥_{reason}.png"
            self.game.save_frame(paths.data(os.path.join("logs", name)), self.game.last_frame)
        except Exception:
            pass


RaidTask = BattleTask           # 舊名稱（v0.3 以前）
