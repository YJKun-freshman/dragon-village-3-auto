# -*- coding: utf-8 -*-
"""
自動釣魚。

每一輪：
    主畫面 → 按釣竿（自動拋竿）→ 等待咬鉤 → 出現「！」→ 連點釣竿 → 結果
      成功：出現魚卡 → 按 X → 回主畫面
      失敗：顯示「哎呀，釣魚失敗了……」→ 自動回主畫面
    → 等冷卻（調節呼吸）→ 下一輪

開始前請先手動進入釣魚畫面（廣場 → 釣魚）。

判斷方式（數值來自 2026-11-05 的連拍分析，見 CHANGELOG）：
- 主畫面：找「圖鑑」「升級」按鈕（樣板）
- 魚餌用完：釣竿按鈕變成紅色「看廣告」（樣板）
- 釣魚中：上方水中框裡的蟲／浮標還在（粉紅色像素數）
- 上鉤：框裡出現橘色「！」（橘色像素數）——只出現約 0.3～0.4 秒，所以用顏色判斷比樣板快又穩
- 拉魚結束：蟲消失（成功或失敗都會），這時立刻停止連點，
  因為成功魚卡上的「排名」按鈕剛好在釣竿按鈕的位置
"""
import os
import time

import cv2

from core import paths
from core.ads import AdCloser, AD_STUCK
from core.task import Task, Param

T = "fishing/templates/"

# ---------------------------------------------------------------- 位置（遊戲畫面比例）
ROD = (0.50, 0.757)                         # 釣竿按鈕中心（找不到樣板時用這個）
R_ROD = (0.30, 0.68, 0.70, 0.84)           # 釣竿／看廣告按鈕範圍
R_BOOK = (0.25, 0.60, 0.50, 0.75)          # 圖鑑按鈕
R_UPGRADE = (0.50, 0.60, 0.75, 0.75)       # 升級按鈕
R_RESULT_X = (0.35, 0.78, 0.65, 0.92)      # 成功魚卡下方的 X
R_FAIL = (0.20, 0.22, 0.80, 0.30)          # 「哎呀，釣魚失敗了……」
R_REELING = (0.20, 0.12, 0.80, 0.19)       # 「正在將魚拉上來。」
PANEL = (0.19, 0.135, 0.81, 0.275)         # 上方水中框的內部
# 廣告的略過／X、「移除廣告高級版」彈窗、Shift+Tab：改用 core.ads.AdCloser（core v0.5.0，照本模組 v0.5.3 搬過去）
# 釣魚自己的彈窗（不是廣告）：先認出標題才按它的 X（釣魚畫面右下角也有一個 X，是離開釣魚，不能亂按）
#   (名稱, 標題樣板, 標題範圍, X 樣板, X 範圍)
POPUPS = [
    ("恢復活力", "彈窗_恢復活力", (0.20, 0.38, 0.80, 0.55), "成功_X", (0.30, 0.72, 0.70, 0.88)),
]
REEL_MAX_SEC = 15                           # 拉魚最多連點幾秒（平常約 4 秒）；超過就停止整個任務
REEL_MAX_CLICKS = 120                       # 拉魚最多點幾下（平常約 30 下）
R_PANEL_L = (0.10, 0.22, 0.30, 0.34)       # 水中框左下角
R_PANEL_R = (0.70, 0.22, 0.90, 0.34)       # 水中框右下角
CARD_RETRY = 3.0                            # 魚卡 X 兩次點擊至少隔幾秒（關閉動畫期間不要再點）
# 自動走到釣魚場：村莊 →（羅盤）→ 選單 →（廣場）→ 廣場 →（小地圖）→ 地圖 →（釣魚場）→ 釣魚畫面
R_COMPASS = (0.35, 0.86, 0.65, 1.0)        # 村莊下方中間的羅盤
R_MENU_PLAZA = (0.35, 0.75, 0.65, 0.90)    # 選單裡的「廣場」
R_HOME = (0.85, 0.60, 1.0, 0.70)           # 廣場右側的回家鍵（釣魚畫面也有）
R_MAP = (0.0, 0.15, 1.0, 0.80)             # 地圖上的「釣魚場」
MINIMAP = (0.121, 0.150)                    # 廣場左上角的小地圖
# 地圖上的建築（好友／公會的圓點會隨機蓋住其中某個 → 任一個認得就算地圖畫面），
# 以及從它推算「釣魚場」位置的偏移（2026-11-10 實測：四個推算結果差 < 0.002）
MAP_MARKS = [("進場_地圖釣魚場", 0.0, 0.0), ("進場_地圖藍光商會", -0.1275, 0.0090),
             ("進場_地圖仲介所", -0.2460, 0.0030), ("進場_地圖髮型沙龍", -0.3672, 0.0065),
             ("進場_地圖流浪商人", 0.1221, -0.1095)]

# ---------------------------------------------------------------- 顏色門檻（HSV，OpenCV 0～180）
# 實測：釣魚中蟲 440～930 點，結束後 0，主畫面 150～280（框外的東西）
WORM_ON = 350
WORM_GONE = 200
# 實測：「！」出現時 400～940 點，沒出現時 < 50
BITE_ON = 250


def _panel(frame):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = PANEL
    return cv2.cvtColor(frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], cv2.COLOR_BGR2HSV)


def worm_pixels(frame):
    """框裡蟲（粉紅色）的像素數。"""
    hsv = _panel(frame)
    m = cv2.inRange(hsv, (0, 90, 170), (9, 230, 255)) | cv2.inRange(hsv, (170, 90, 170), (180, 230, 255))
    return cv2.countNonZero(m)


def bite_pixels(frame):
    """框裡「！」（橘黃色）的像素數。"""
    return cv2.countNonZero(cv2.inRange(_panel(frame), (10, 150, 200), (30, 255, 255)))


class Fishing(Task):
    _last_x = 0.0                                # 上次按魚卡 X 的時間
    _adc = None                                  # core.ads.AdCloser（第一次用到時建立）
    _card_clicks = 0                             # 這次等待中按了幾次魚卡 X
    _pop_clicks = 0                              # 這次等待中按了幾次恢復活力 X
    path = ("釣魚",)
    description = "自動釣魚。可以從村莊、廣場或釣魚畫面開始（會自動走到釣魚場）。遊戲視窗請用 9:16。"
    params = [
        Param("max_rounds", "釣魚次數上限", int, default=100, min=1, max=9999,
              help="魚餌一次最多 20 個；沒開「自動看廣告」時用完就停止"),
        Param("watch_ads", "魚餌用完時自動看廣告", bool, default=False,
              help="遊戲視窗請調成 9:16（直的），廣告的略過鍵才會在畫面裡。"
                   "自動看廣告比較容易被判定異常，請自行評估"),
        Param("max_ads", "最多看幾次廣告", int, default=5, min=1, max=50),
        Param("auto_enter", "自動走到釣魚場", bool, default=True,
              help="從村莊或廣場開始時，自動走到釣魚場（羅盤 → 廣場 → 小地圖 → 釣魚場）"),
        Param("react_delay", "上鉤後延遲點擊(秒)", float, default=0.0, min=0.0, max=1.0,
              help="「！」只出現約 0.3 秒，建議 0"),
        Param("click_interval", "連點間隔(秒)", float, default=0.06, min=0.02, max=0.5,
              help="拉魚時每次點擊的間隔，越小點越快"),
        Param("cast_delay", "每輪間隔(秒)", float, default=5.0, min=0.0, max=60.0,
              help="回到主畫面後等多久再拋竿（遊戲有「調節呼吸」冷卻）"),
        Param("bite_timeout", "等待咬鉤最長(秒)", float, default=60.0, min=5.0, max=600.0),
    ]

    # ------------------------------------------------------------ 主流程
    def run(self):
        v = self.values
        self.ok = self.fail = 0
        self.rod = ROD
        self._timeouts = 0
        self.ads = 0
        self._last_x = 0.0
        self._adc = AdCloser(self.game, log=self.log, debug_name="釣魚")
        self._measure_speed()

        if not self._wait_main(timeout=5) and not (v["auto_enter"] and self._go_fishing()):
            self._debug("開始時不在釣魚畫面")
            self.log("❌ 找不到釣魚畫面。請先進入「廣場 → 釣魚」，看得到釣竿按鈕後再按開始。")
            return

        for i in range(v["max_rounds"]):
            if self.should_stop():
                break
            self.set_progress(f"第 {i + 1}/{v['max_rounds']} 輪　成功 {self.ok}　失敗 {self.fail}")
            if not self._one_round(i + 1):
                break

        self.log(f"釣魚結束：成功 {self.ok} 次、失敗 {self.fail} 次")
        self.set_progress(f"結束　成功 {self.ok}　失敗 {self.fail}")

    def _one_round(self, n):
        """回傳 False 代表要停止整個任務。"""
        g = self.game

        # 1. 主畫面：檢查魚餌、等冷卻、拋竿
        frame = g.capture()
        if self._no_bait(frame) and not self._refill():
            return False
        if not self._cast(first=(n == 1)):
            return False

        # 2. 等「！」
        self.log(f"第 {n} 輪：已拋竿，等待咬鉤…")
        result = self._wait_bite()
        if result != "bite":
            return result != "stop"

        # 3. 連點到結束
        if self.values["react_delay"] > 0 and not self.sleep(self.values["react_delay"]):
            return False
        t0 = time.monotonic()
        clicks = self._reel()
        if clicks is None:
            return False

        # 4. 結果
        res = self._result()
        if res == "ok":
            self.ok += 1
            self.log(f"第 {n} 輪：✅ 成功（拉魚 {time.monotonic() - t0:.1f} 秒、點了 {clicks} 下）")
        elif res == "fail":
            self.fail += 1
            self.log(f"第 {n} 輪：❌ 失敗")
        elif res == "stop":
            return False
        else:
            self._debug("結果畫面不認得")
            self.log(f"第 {n} 輪：⚠ 看不出結果，嘗試回到主畫面")

        if not self._wait_main(timeout=20):
            self._debug("回不到主畫面")
            self.log("❌ 一直回不到釣魚畫面，已停止。截圖存在 logs 資料夾。")
            return False
        return True

    # ------------------------------------------------------------ 各階段
    def _cast(self, first=False):
        """等冷卻後按釣竿，確認有拋出去。"""
        if not first and not self.sleep(self.values["cast_delay"]):
            return False
        g = self.game
        for attempt in range(5):
            frame = g.capture()
            if self._no_bait(frame):
                if not self._refill():
                    return False
                frame = g.capture()
            # 🔒 安全：一定要是釣魚畫面、沒有「看廣告」、沒有水中框才按
            #    釣竿按鈕常被玩家名字、搖桿蓋住（實測 0.77），所以不要求釣竿樣板，改用圖鑑／升級按鈕確認畫面
            if not (self._is_main(frame) and not self._no_bait(frame) and not self._in_panel(frame)
                    and not self._ad_visible(frame)):
                ok = self._wait_main(timeout=20) or (self.values["auto_enter"] and self._go_fishing())
                if not ok or not self.sleep(1.0):
                    self._debug("拋竿前畫面不對")
                    self.log("❌ 準備拋竿時不在釣魚畫面，已停止。截圖存在 logs 資料夾。")
                    return False
                continue
            m = g.find(T + "釣竿按鈕.png", region=R_ROD, threshold=0.6, frame=frame)
            if m and abs(m.x - ROD[0]) < 0.03 and abs(m.y - ROD[1]) < 0.03:
                self.rod = (m.x, m.y)                # 找得到就用找到的位置，找不到就用固定位置
            else:
                self.rod = ROD
            g.click(*self.rod)
            # 拋竿成功 → 出現水中框、框裡有蟲
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                if not self.sleep(0.1):
                    return False
                f = g.capture()
                if self._in_panel(f) and worm_pixels(f) >= WORM_ON:
                    return True
            # 還在冷卻（「正在調節呼吸」）→ 等一下再試
            if not self.sleep(1.5):
                return False
        self._debug("拋竿失敗")
        self.log("❌ 按了 5 次釣竿都沒拋出去，已停止。截圖存在 logs 資料夾。")
        return False

    def _wait_bite(self):
        """回傳 "bite" / "stop" / "skip"（超時，這輪跳過）。"""
        g = self.game
        end = time.monotonic() + self.values["bite_timeout"]
        lost = 0
        while time.monotonic() < end:
            if self.should_stop():
                return "stop"
            f = g.capture()
            panel = self._in_panel(f)
            if panel and worm_pixels(f) >= WORM_ON and bite_pixels(f) >= BITE_ON:
                g.click(*self.rod)                 # 第一下馬上點，「！」很短
                self._timeouts = 0
                return "bite"
            if not panel:
                lost += 1
                if lost >= 10:                     # 約 0.3 秒都沒看到水中框 → 不在釣魚中
                    self._debug("等待咬鉤時畫面不對")
                    self.log("⚠ 等待咬鉤時畫面變了，嘗試回到主畫面")
                    return "skip" if self._wait_main(timeout=10) else "stop"
            else:
                lost = 0
        self._timeouts += 1
        self._debug("等待咬鉤超時")
        self.log(f"⚠ 等了 {self.values['bite_timeout']:.0f} 秒都沒有上鉤")
        if self._timeouts >= 2:
            self.log("❌ 連續 2 次等不到上鉤，已停止。截圖存在 logs 資料夾。")
            return "stop"
        return "skip" if self._wait_main(timeout=30) else "stop"

    def _reel(self):
        """連點釣竿直到蟲消失（拉上來或跑掉）。回傳點擊次數；被停止回傳 None。"""
        g = self.game
        interval = self.values["click_interval"]
        clicks = 1                                 # _wait_bite 已經點了第一下
        gone = 0
        end = time.monotonic() + REEL_MAX_SEC
        while time.monotonic() < end and clicks < REEL_MAX_CLICKS:
            if self.should_stop():
                return None
            t = time.monotonic()
            f = g.capture()
            # 🔒 安全：看不到水中框或蟲 → 不是在拉魚，立刻停手（不在廣告或其他畫面上亂點）
            if not self._in_panel(f) or worm_pixels(f) < WORM_GONE:
                gone += 1
                if gone >= 2:                      # 連續 2 張 → 結束，不要再點
                    return clicks
                continue
            gone = 0
            g.click(*self.rod)
            clicks += 1
            rest = interval - (time.monotonic() - t)
            if rest > 0 and not self.sleep(rest):
                return None
        self._debug("連點太久")
        self.log(f"❌ 拉魚連點超過 {REEL_MAX_SEC} 秒／{REEL_MAX_CLICKS} 下還沒結束，為了安全已停止。截圖存在 logs 資料夾。")
        return None

    def _result(self):
        """回傳 "ok" / "fail" / "unknown" / "stop"。"""
        g = self.game
        end = time.monotonic() + 6
        while time.monotonic() < end:
            if self.should_stop():
                return "stop"
            f = g.capture()
            if g.find(T + "成功_X.png", region=R_RESULT_X, threshold=0.85, frame=f):
                m = self._card_x_stable()
                if m is None:
                    if not self.sleep(0.1):
                        return "stop"
                    continue                       # 還在動畫中，再看一次
                g.click_match(m)
                self._last_x = time.monotonic()
                return "ok"                        # 沒關掉的話 _wait_main 會再按
            if g.find(T + "失敗.png", region=R_FAIL, threshold=0.85, frame=f):
                return "fail"
            if not self.sleep(0.1):
                return "stop"
        return "unknown"

    # ------------------------------------------------------------ 魚餌／廣告
    def _refill(self):
        """魚餌用完。回傳 True = 已補充，可以繼續。"""
        v = self.values
        if not v["watch_ads"]:
            self.log("🪱 魚餌用完了（0/20），已停止。請看廣告補充魚餌後再按開始。"
                     "（或在參數勾選「魚餌用完時自動看廣告」）")
            return False
        if self.ads >= v["max_ads"]:
            self.log(f"🪱 魚餌用完了，已經看了 {self.ads} 次廣告（上限 {v['max_ads']}），停止。")
            return False
        while self.ads < v["max_ads"]:
            self.ads += 1
            self.log(f"🪱 魚餌用完了，自動看廣告（第 {self.ads} 次）…")
            r = self._watch_ad()
            if r is True:
                self.log("📺 廣告結束，魚餌已補充")
                return True
            if r != "nobait":
                return False
            self.log("⚠ 廣告關掉了但魚餌沒有補充（可能是倒數沒跑完就關掉），再看一次")
        self.log(f"🪱 已經看了 {self.ads} 次廣告（上限 {v['max_ads']}），停止。")
        return False

    def _watch_ad(self):
        """True = 補到魚餌；"nobait" = 回到釣魚但魚餌還是 0；False = 卡住／停止。"""
        g = self.game
        # 1. 按「看廣告」，確認有進入廣告：看廣告按鈕消失，或是看得到廣告的關閉鈕
        #    （只蓋住上半部的廣告，下面的看廣告按鈕還看得到，不能再按）
        for _ in range(3):
            f = g.capture()
            if self._ad_visible(f):
                break
            m = g.find(T + "看廣告.png", region=R_ROD, threshold=0.85, frame=f)
            if not m:
                break
            g.click_match(m)
            started = False
            end = time.monotonic() + 5
            while time.monotonic() < end:
                if not self.sleep(0.3):
                    return False
                f = g.capture()
                if self._ad_visible(f) or not self._no_bait(f):
                    started = True
                    break
            if started:
                break
        else:
            self._debug("按看廣告沒反應")
            self.log("❌ 按了 3 次「看廣告」都沒反應，已停止。")
            return False

        # 🔒 安全：等廣告真的蓋住畫面（看不到釣魚畫面）。看廣告按鈕消失得比廣告出現早，
        #    之前就是在這段空檔誤以為「廣告結束」，接著把廣告當成釣魚在連點
        end = time.monotonic() + 20
        while True:
            f = g.capture()
            if not self._is_main(f) or self._ad_visible(f):
                break                              # 廣告出現（只蓋住上半部的廣告也算）
            if time.monotonic() >= end:
                f = g.capture()
                if not self._no_bait(f):
                    return True                    # 沒看到廣告但魚餌已經有了
                self._debug("廣告沒出現")
                self.log("❌ 按了「看廣告」20 秒都沒出現廣告，已停止。")
                return False
            if not self.sleep(0.3):
                return False
        self.log("📺 廣告開始")

        # 2. 一直找略過／X（必要時送 Shift+Tab），直到回到釣魚畫面
        if self._wait_main(timeout=AD_STUCK):
            return "nobait" if self._no_bait(g.capture()) else True
        self._ads.save_debug("廣告卡住")             # 16:9 時存整個視窗
        self.log("❌ 廣告關不掉，已停止。請手動關掉廣告（可以試試 Shift+Tab），"
                 "截圖存在 logs 資料夾，可以傳給開發者新增樣板。")
        return False

    # ------------------------------------------------------------ 自動走到釣魚場
    def _go_fishing(self):
        """從村莊／廣場走到釣魚場。每一步都先認出畫面才按，認不出來就放棄。回傳是否到達。"""
        g = self.game
        self.log("🚶 自動前往釣魚場…")
        now = time.monotonic
        end = now() + 90
        last_act = now()
        walking_until = 0.0                        # 按了「釣魚場」後角色在走路，這段時間不要再點小地圖
        tries = {"羅盤": 0, "廣場": 0, "小地圖": 0, "釣魚場": 0}

        def act(name, rx, ry, wait):
            if tries[name] >= 3:
                return False
            tries[name] += 1
            g.click(rx, ry)
            self.log(f"🚶 按「{name}」")
            return self.sleep(wait)

        while now() < end:
            if self.should_stop():
                return False
            f = g.capture()
            if self._is_main(f) and not self._in_panel(f):
                if not self.sleep(0.5):
                    return False
                if self._is_main(g.capture()):
                    self.log("🚶 已到達釣魚場")
                    return True
                continue
            spot = self._map_fishing_spot(f)
            if spot:
                if not act("釣魚場", spot[0], spot[1], 2.0):
                    break
                walking_until = now() + 30
                last_act = now()
                continue
            m = g.find(T + "進場_廣場.png", region=R_MENU_PLAZA, threshold=0.85, frame=f)
            if m:
                if not act("廣場", m.x, m.y, 4.0):
                    break
                last_act = now()
                continue
            m = g.find(T + "進場_羅盤.png", region=R_COMPASS, threshold=0.85, frame=f)
            if m:
                if not act("羅盤", m.x, m.y, 1.5):
                    break
                last_act = now()
                continue
            if (now() > walking_until and not self._in_panel(f)
                    and g.find(T + "進場_回家.png", region=R_HOME, threshold=0.85, frame=f)):
                if not act("小地圖", *MINIMAP, 2.0):
                    break
                last_act = now()
                continue
            if now() - last_act > 20:              # 20 秒都認不出畫面
                break
            if not self.sleep(0.5):
                return False
        self._debug("走不到釣魚場")
        self.log("❌ 自動前往釣魚場失敗，請手動走到釣魚場後再按開始。截圖存在 logs 資料夾。")
        return False

    def _map_fishing_spot(self, frame):
        """地圖畫面 → 「釣魚場」的位置 (x, y)；不是地圖 → None。
        先找釣魚場本身，被圓點蓋住時改用其他建築推算位置。"""
        g = self.game
        for name, dx, dy in MAP_MARKS:
            m = g.find(T + name + ".png", region=R_MAP, threshold=0.85, frame=frame)
            if m:
                return m.x + dx, m.y + dy
        return None

    # ------------------------------------------------------------ 判斷
    def _is_main(self, frame):
        """釣魚畫面（還沒拋竿）。依據：升級／圖鑑按鈕（主畫面 0.85～1.00，其他 ≤ 0.61），
        或「看得到釣竿按鈕但沒有水中框」（等待咬鉤時釣竿按鈕也在，但有水中框）。"""
        g = self.game
        if (g.find(T + "升級按鈕.png", region=R_UPGRADE, threshold=0.75, frame=frame)
                or g.find(T + "圖鑑按鈕.png", region=R_BOOK, threshold=0.75, frame=frame)):
            return True
        return bool(g.find(T + "釣竿按鈕.png", region=R_ROD, threshold=0.85, frame=frame)
                    and not self._in_panel(frame))

    @property
    def _ads(self):
        if self._adc is None:
            self._adc = AdCloser(self.game, log=self.log, debug_name="釣魚")
        return self._adc

    def _ad_visible(self, frame=None):
        """畫面上看得到任何廣告關閉鈕（core.ads）。有些廣告只蓋住上半部，
        所以「看得到廣告」優先於「看得到釣魚畫面」。16:9 時看整個視窗（關閉鈕在黑邊上）。"""
        if frame is None or self.game.letterboxed:
            frame = self._ads.frames()[1]
        return self._ads.visible(frame)

    def _in_panel(self, frame):
        """畫面上有釣魚的水中框（左下、右下角都在）。實測釣魚中 0.97～1.00，廣告和其他畫面 ≤ 0.40。"""
        g = self.game
        return bool(g.find(T + "釣魚框_左下.png", region=R_PANEL_L, threshold=0.8, frame=frame)
                    and g.find(T + "釣魚框_右下.png", region=R_PANEL_R, threshold=0.8, frame=frame))

    def _find_popup(self, frame):
        """釣魚自己認得的遊戲彈窗（恢復活力）→ (說明, 要按的 Match 或 None)；沒有 → None。
        「移除廣告高級版」由 core.ads 處理。"""
        g = self.game
        for name, title, tr, xt, xr in POPUPS:
            if g.find(T + title + ".png", region=tr, threshold=0.85, frame=frame):
                return f"{name}：按 X", g.find(T + xt + ".png", region=xr, threshold=0.85, frame=frame)
        return None

    def _card_x_stable(self):
        """魚卡停穩了才回傳 X 的位置：間隔 0.4 秒看兩次，都找到而且位置一樣。
        滑進來或關閉中的魚卡會回傳 None，避免點到底下的道具欄。"""
        g = self.game
        a = g.find(T + "成功_X.png", region=R_RESULT_X, threshold=0.9)
        if not a or not self.sleep(0.4):
            return None
        b = g.find(T + "成功_X.png", region=R_RESULT_X, threshold=0.9)
        if b and abs(a.x - b.x) < 0.01 and abs(a.y - b.y) < 0.01:
            return b
        return None

    def _no_bait(self, frame):
        return bool(self.game.find(T + "看廣告.png", region=R_ROD, threshold=0.85, frame=frame))

    def _wait_main(self, timeout, need_bait=False):
        """
        等回到釣魚畫面（need_bait=True 時還要「看廣告」按鈕消失）。用 core.ads.AdCloser.close_until：
        - 廣告的略過／Skip／X、「移除廣告高級版」彈窗、Shift+Tab、16:9 黑邊上的關閉鈕：core 處理
        - 釣魚自己的（_extra）：恢復活力彈窗按 X；成功魚卡停穩才按 X，兩次至少隔 CARD_RETRY 秒，最多 10 次
        有在處理就自動延長等待時間。
        """
        self._card_clicks = self._pop_clicks = 0

        def done(f):
            return self._is_main(f) and not (need_bait and self._no_bait(f))

        return self._ads.close_until(done=done, timeout=timeout, extra=self._extra)

    def _extra(self, f):
        """給 AdCloser 的釣魚專用處理。回傳 "acted"（按了東西）、"busy"（有東西但先不按）、None。"""
        g = self.game
        popup = self._find_popup(f) if self._pop_clicks < 10 else None
        if popup:
            name, x = popup
            if x:
                g.click_match(x)
                self._pop_clicks += 1
                self.log(f"🗙 遊戲彈窗 {name}")
                self.sleep(1.5)
                return "acted"
            return "busy"
        if g.find(T + "成功_X.png", region=R_RESULT_X, threshold=0.85, frame=f):
            # 剛按過 X 的話，魚卡可能正在關閉動畫，這時再點會點到底下的道具欄 → 至少隔 CARD_RETRY 秒，而且要魚卡停穩
            if self._card_clicks < 10 and time.monotonic() - self._last_x >= CARD_RETRY:
                m = self._card_x_stable()
                if m:
                    g.click_match(m)
                    self._card_clicks += 1
                    self._last_x = time.monotonic()
                    return "acted"
            return "busy"                          # 魚卡還在 → 不送 Shift+Tab
        return None

    # ------------------------------------------------------------ 其他
    def _measure_speed(self):
        g = self.game
        t = time.perf_counter()
        for _ in range(5):
            f = g.capture()
            worm_pixels(f)
            bite_pixels(f)
        ms = (time.perf_counter() - t) / 5 * 1000
        self.log(f"截圖＋判斷一次約 {ms:.0f} ms")
        if ms > 120:
            self.log("⚠ 截圖偏慢，可能來不及在「！」出現時按到。可以試著把遊戲視窗調小一點。")

    def _debug(self, reason):
        """存目前畫面到 logs/，方便之後除錯。"""
        try:
            name = time.strftime("%m%d_%H%M%S") + f"_釣魚_{reason}.png"
            path = paths.data(os.path.join("logs", name))
            self.game.save_frame(path, self.game.last_frame)
        except Exception:
            pass
