# -*- coding: utf-8 -*-
"""
關廣告（釣魚、戰鬥共用）。邏輯照釣魚 v0.5.3 的 `_wait_main` 搬過來（實測 87/87、多次自動看廣告）。

    from core.ads import AdCloser
    ads = AdCloser(game, log=self.log)              # 一個任務建一個就好（「今天不再顯示」只勾一次）
    ok = ads.close_until(done=self._is_main, timeout=45)

- done(frame)：呼叫端判斷「回到我的畫面了」（frame 是遊戲畫面）。看得到廣告關閉鈕時不算回到原畫面
  （有些廣告只蓋住上半部，下面還看得到原畫面）
- 途中自動處理：
  - 「移除廣告高級版」彈窗：先勾「今天不再顯示」再按「僅觀看廣告」（絕不按「訂閱」）
  - 廣告的略過／Skip／X：找到就按（寬膠囊「已發放獎勵小」按右端的 ✕；「✕ N 秒後可獲獎勵」等 30 秒沒別的可按才按）
  - 超過 SPEAKER_AFTER 秒都沒東西可按、看得到廣告的喇叭：按一下喇叭（廣告卡住時進度條會繼續跑），最多 3 次
  - 超過 KEY_AFTER 秒都沒東西可按：送 Shift+Tab（有些廣告要按了才出現 X），最多 5 次
  - 有在處理就自動延長等待時間
- extra(frame)：呼叫端自己的處理（例如釣魚的魚卡 X）。回傳 "acted"（按了東西）、"busy"（有東西在但先不按，
  不要送 Shift+Tab）、None（沒事）。在彈窗之後、廣告之前呼叫，跟釣魚原本的順序一樣
- 16:9 視窗（有黑邊）：廣告會播滿整個視窗、關閉鈕在黑邊上 → 自動改看整個視窗、用 click_window() 點
"""
import os
import time

from . import paths

T = "core/templates/ads/"

# 範圍是比例：9:16 時是遊戲畫面；16:9 時是整個視窗
R_AD_CLOSE = (0.80, 0.0, 1.0, 0.60)        # 大部分廣告的略過／X 在右上～右側
R_AD_TOPLEFT = (0.0, 0.0, 0.35, 0.08)      # 「✕ 已發放獎勵」在左上
# (樣板, 範圍, 至少等幾秒沒其他東西可按才按)
CLOSE = [("廣告_略過", R_AD_CLOSE, 0), ("廣告_Skip", R_AD_CLOSE, 0),
         # Meta 廣告的「Skip ▶|」深色膠囊，大一號（約 1.45 倍）；其他畫面最高 0.56
         ("廣告_Skip大", R_AD_CLOSE, 0),
         ("廣告_X_圓淺", R_AD_CLOSE, 0),
         ("廣告_X_圓深", R_AD_CLOSE, 0), ("廣告_X_黑圓", R_AD_CLOSE, 0), ("廣告_X_灰圓", R_AD_CLOSE, 0),
         ("廣告_X_白圓", R_AD_CLOSE, 0), ("廣告_X_細", R_AD_CLOSE, 0),
         # 16:9 視窗：廣告播滿整個視窗，灰色圓 X 在整個視窗右上角（黑邊上）。9:16 的非廣告畫面最高 0.71
         ("廣告_X_灰圓16比9", R_AD_CLOSE, 0),
         ("廣告_X_已發放獎勵", R_AD_TOPLEFT, 0), ("廣告_X_已發放獎勵深", R_AD_TOPLEFT, 0),
         ("廣告_X_已發放獎勵右", (0.60, 0.0, 1.0, 0.08), 0),
         ("廣告_X_已發放獎勵小", (0.60, 0.0, 1.0, 0.06), 0),
         # 直式廣告（在遊戲畫面範圍內）左上角的「✕ 已發放獎勵」大一號版本、「▷| 略過影片」（使用者 16:9 截圖；9:16 也看過）
         ("廣告_X_已發放獎勵左16比9", (0.0, 0.0, 0.45, 0.08), 0),
         ("廣告_略過影片", (0.0, 0.0, 0.45, 0.08), 0),
         # 上方白色橫幅廣告（例：App 安裝廣告）左上角的黑色 ✕；其他畫面最高 0.65
         ("廣告_X_白底黑", (0.0, 0.0, 0.20, 0.08), 0),
         # 16:9 播滿整個視窗的影片廣告右上角的「⏭」白色膠囊（略過）；其他畫面最高 0.50
         ("廣告_跳過膠囊16比9", (0.85, 0.0, 1.0, 0.08), 0),
         # 同位置只有「▶|」小圖示（灰色、可能還不能按）：5 秒沒別的可按才按；其他畫面最高 0.68
         ("廣告_跳過圖示16比9", (0.90, 0.0, 1.0, 0.08), 5),
         # 16:9：「已發放獎勵 ✕」膠囊在整個視窗右上角（黑邊上），其他畫面最高 0.45
         ("廣告_X_已發放獎勵16比9", (0.60, 0.0, 1.0, 0.08), 0),
         # 「✕ N 秒後可獲獎勵」：倒數有時會卡住不動（廣告其實已經播完），等 30 秒後直接按
         ("廣告_X_倒數", R_AD_TOPLEFT, 30)]
CLICK_AT = {"廣告_X_已發放獎勵小": 0.92, "廣告_X_已發放獎勵16比9": 0.835, "廣告_X_已發放獎勵左16比9": 0.15}     # 寬的膠囊鈕：按在樣板寬度的這個位置（✕ 在右端），其他按中心
THRESHOLD = 0.8                              # 實測所有廣告樣板在釣魚畫面上最高 0.63

# 「移除廣告高級版」（遊戲畫面座標）
R_ADS_ONLY = (0.45, 0.75, 0.95, 0.90)
R_NOT_TODAY = (0.10, 0.86, 0.45, 0.93)
R_CHECKBOX = (0.05, 0.86, 0.20, 0.93)

# 16:9 視窗時，樣板也用這些倍率再試（16:9 的廣告按鈕常常比較大）。
# 實測：16:9 非廣告畫面（整個視窗、遊戲畫面）所有樣板在這些倍率下都 < 0.8
LETTERBOX_SCALES = (1.0, 1.2, 1.4)

# 廣告的喇叭（白色喇叭字形，疊在影片上）：使用者發現廣告有時候會卡住不動，按一下喇叭進度條才會繼續跑。
# 背景是影片、每次不一樣 → 先把畫面變成「很亮的點 = 1、其他 = 0」再比對字形。實測本張 1.00、其他 230 張畫面 ≤ 0.53
SPEAKER = "廣告_喇叭_白字"
SPEAKER_REGION = (0.0, 0.0, 1.0, 0.10)     # 遊戲畫面上方
SPEAKER_WHITE = 215
SPEAKER_THRESHOLD = 0.75
SPEAKER_SCALES = (1.0, 0.85, 1.2)
# 16:9 播滿整個視窗的影片廣告：左上角灰色圓形喇叭（一般樣板比對，整個視窗）；其他畫面最高 0.69
SPEAKER_ROUND = "廣告_喇叭_圓16比9"
SPEAKER_ROUND_REGION = (0.0, 0.0, 0.10, 0.10)
SPEAKER_AFTER = 10     # 這麼多秒沒東西可按 → 先試按喇叭（在 Shift+Tab 之前）
MAX_SPEAKER = 3

AD_STUCK = 45          # 這麼多秒都沒有可以按的東西 → 當作卡住
KEY_AFTER = 15         # 這麼多秒沒東西可按 → 送 Shift+Tab
MAX_KEYS = 5
MAX_AD_CLICKS = 15
MAX_POPUP_CLICKS = 10


class AdCloser:
    def __init__(self, game, log=None, stop=None, scales=None, debug_name="廣告"):
        """
        log         log(text)；Task 裡傳 self.log
        stop        threading.Event；不給就用 game.stop_event
        scales      找關閉鈕的倍率（16:9 廣告如果大小不同再開，預設關閉）
        debug_name  卡住時存截圖的檔名前綴，例 "釣魚"、"戰鬥"
        """
        self.game = game
        self._log = log or (lambda t: None)
        self._stop = stop
        self.scales = scales
        self.debug_name = debug_name
        self.tick_tries = 0      # 「今天不再顯示」勾了幾次（同一個任務最多 2 次）

    # ------------------------------------------------------------ 小工具
    def log(self, text):
        self._log(text)

    def _stopped(self):
        ev = self._stop or self.game.stop_event
        return bool(ev and ev.is_set())

    def sleep(self, seconds):
        """可中斷；回傳 False = 被停止。"""
        ev = self._stop or self.game.stop_event
        if ev is None:
            time.sleep(seconds)
            return True
        return not ev.wait(seconds)

    def frames(self):
        """(遊戲畫面, 找廣告用的畫面)。16:9 有黑邊時找廣告用整個視窗。"""
        g = self.game
        gf, wf = g.capture_both(window=True)
        return gf, (wf if g.letterboxed else gf)

    # ------------------------------------------------------------ 判斷
    def _targets(self, frame):
        """
        要在哪些畫面上找關閉鈕 → [(種類, 畫面, 倍率)]。
        9:16：只看遊戲畫面（跟以前一樣）。
        16:9（傳進來的是整個視窗畫面）：廣告有兩種——播滿整個視窗的（關閉鈕在黑邊上）、
        直式在遊戲畫面範圍內的（關閉鈕在遊戲畫面的角落，而且常常比 9:16 大一號）→ 兩個都找，都多試幾個倍率。
        """
        if frame is not None and frame.shape[1] > frame.shape[0] * 1.2 and self.game.last_frame is not None:
            sc = self.scales or LETTERBOX_SCALES
            return [("game", self.game.last_frame, sc), ("window", frame, sc)]
        return [("game", frame, self.scales)]

    def _click(self, kind, rx, ry):
        if kind == "window":
            self.game.click_window(rx, ry)
        else:
            self.game.click(rx, ry)

    # ------------------------------------------------------------ 判斷
    def visible(self, ad_frame):
        """看得到任何廣告關閉鈕（不管延遲）。ad_frame 用 frames()[1]。"""
        g = self.game
        return any(g.find(T + n + ".png", region=r, threshold=THRESHOLD, frame=f, scales=sc)
                   for _, f, sc in self._targets(ad_frame) for n, r, _ in CLOSE)

    def find_popup(self, frame):
        """「移除廣告高級版」→ (說明, 要按的 Match)；沒有 → None。frame 是遊戲畫面。"""
        g = self.game
        only = g.find(T + "彈窗_僅觀看廣告.png", region=R_ADS_ONLY, threshold=0.8, frame=frame)
        if only and g.find(T + "彈窗_今天不再顯示.png", region=R_NOT_TODAY, threshold=0.8, frame=frame):
            box = g.find(T + "彈窗_勾選框.png", region=R_CHECKBOX, threshold=0.85, frame=frame)
            if box and self.tick_tries < 2:         # 還沒勾 → 先勾「今天不再顯示」
                self.tick_tries += 1
                return "移除廣告高級版：勾選「今天不再顯示」", box
            return "移除廣告高級版：按「僅觀看廣告」", only
        return None

    def find_close(self, ad_frame, idle_seconds=999.0):
        """要按的關閉鈕 → (名稱, 比例 x, 比例 y, 種類 "game"/"window")；沒有 → None。
        idle_seconds = 多久沒按東西了（延遲用）。"""
        g = self.game
        targets = self._targets(ad_frame)
        for name, region, delay in CLOSE:
            if delay and idle_seconds < delay:
                continue
            for kind, f, sc in targets:
                m = g.find(T + name + ".png", region=region, threshold=THRESHOLD, frame=f, scales=sc)
                if m:
                    x = m.x - m.w / 2 + m.w * CLICK_AT[name] if name in CLICK_AT else m.x
                    return name, x, m.y, kind
        return None

    def speaker(self, game_frame, ad_frame=None):
        """廣告的喇叭 → (比例 x, 比例 y, 種類)；沒有 → None。
        先找遊戲畫面上方的白色喇叭字形；16:9 時再找整個視窗左上角的圓形喇叭。"""
        hit = self.find_speaker(game_frame)
        if hit:
            return hit[0], hit[1], "game"
        if ad_frame is not None and ad_frame.shape[1] > ad_frame.shape[0] * 1.2:
            m = self.game.find(T + SPEAKER_ROUND + ".png", region=SPEAKER_ROUND_REGION, threshold=THRESHOLD,
                               frame=ad_frame, scales=LETTERBOX_SCALES)
            if m:
                return m.x, m.y, "window"
        return None

    def find_speaker(self, game_frame):
        """廣告的白色喇叭字形 → (比例 x, 比例 y)；沒有 → None。只看遊戲畫面上方。"""
        import cv2
        import numpy as np
        from . import vision
        if game_frame is None:
            return None
        tpl = vision.load_template(T + SPEAKER + ".png").image
        tpl = (cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) > 127).astype(np.float32)
        h, w = game_frame.shape[:2]
        x0, y0, x1, y1 = SPEAKER_REGION
        ox, oy = int(x0 * w), int(y0 * h)
        roi = game_frame[oy:int(y1 * h), ox:int(x1 * w)]
        b = (cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) >= SPEAKER_WHITE).astype(np.float32)
        for sc in SPEAKER_SCALES:
            t = tpl if sc == 1.0 else (cv2.resize(tpl, None, fx=sc, fy=sc) > 0.5).astype(np.float32)
            if b.shape[0] < t.shape[0] or b.shape[1] < t.shape[1]:
                continue
            r = np.nan_to_num(cv2.matchTemplate(b, t, cv2.TM_CCOEFF_NORMED))
            _, mx, _, (lx, ly) = cv2.minMaxLoc(r)
            if mx >= SPEAKER_THRESHOLD:
                return (ox + lx + t.shape[1] / 2) / w, (oy + ly + t.shape[0] / 2) / h
        return None

    # ------------------------------------------------------------ 主流程
    def close_until(self, done, timeout=AD_STUCK, extra=None, debug_on_timeout=None):
        """
        關廣告直到 done(遊戲畫面) 為真、而且看不到廣告。回傳 True = 回到原畫面；False = 逾時或被停止。
        確認回到原畫面要隔一下再看一次：這次有按過廣告 → 1 秒，否則 0.5 秒（跟釣魚一樣）。
        debug_on_timeout：逾時時存截圖的原因文字（例 "廣告卡住"），None = 不存
        """
        g = self.game
        now = time.monotonic
        start = last_act = last_key = now()
        end = start + timeout
        ad = keys = pop = spk = 0
        last_spk = 0.0
        while True:
            if self._stopped():
                return False
            gf, af = self.frames()
            if done(gf) and not self.visible(af):
                # 🔒 隔一下再確認一次，避免轉場時一閃而過的畫面
                if not self.sleep(1.0 if ad else 0.5):
                    return False
                gf, af = self.frames()
                if done(gf) and not self.visible(af):
                    return True
                if now() >= end:
                    return False
                continue
            acted = busy = False
            popup = self.find_popup(gf) if pop < MAX_POPUP_CLICKS else None
            if popup:
                name, m = popup
                if m:
                    g.click_match(m)
                    pop += 1
                    acted = True
                    self.log(f"🗙 遊戲彈窗 {name}")
                    if not self.sleep(1.5):
                        return False
                busy = True
            else:
                r = extra(gf) if extra else None
                if r == "acted":
                    acted = busy = True
                elif r == "busy":
                    busy = True
                elif ad < MAX_AD_CLICKS:
                    hit = self.find_close(af, now() - last_act)
                    if hit:
                        name, x, y, kind = hit
                        self._click(kind, x, y)
                        ad += 1
                        acted = busy = True
                        self.log(f"📺 按下「{name.replace('廣告_', '')}」（{now() - start:.0f} 秒）")
                        if not self.sleep(2.0):
                            return False
            t = now()
            if acted:
                last_act = t
                end = max(end, t + AD_STUCK)
            elif (not busy and spk < MAX_SPEAKER and t - last_act >= SPEAKER_AFTER
                  and t - last_spk >= SPEAKER_AFTER and self.speaker(gf, af)):
                # 廣告卡住不動：按一下喇叭，進度條常常就會繼續跑（使用者發現的）
                x, y, kind = self.speaker(gf, af)
                self._click(kind, x, y)
                spk += 1
                last_spk = t
                end = max(end, t + KEY_AFTER + 2)
                self.log(f"🔈 {t - last_act:.0f} 秒沒有可以按的，按一下廣告的喇叭")
            elif not busy and keys < MAX_KEYS and t - last_act >= KEY_AFTER and t - last_key >= KEY_AFTER:
                try:
                    g.key("shift", "tab")
                    self.log(f"⌨ {t - last_act:.0f} 秒沒有可以按的，送出 Shift+Tab")
                except Exception as e:                  # noqa: BLE001
                    self.log(f"⚠ 送出 Shift+Tab 失敗：{e}")
                keys += 1
                last_key = t
                end = max(end, t + KEY_AFTER + 2)
            if t >= end or not self.sleep(0.3):
                if t >= end and debug_on_timeout:
                    self.save_debug(debug_on_timeout)
                return False

    def save_debug(self, reason):
        """存目前畫面（16:9 時存整個視窗）到 logs\\，檔名 MMDD_HHMMSS_<debug_name>_<reason>.png。"""
        try:
            g = self.game
            frame = g.last_window if (g.letterboxed and g.last_window is not None) else g.last_frame
            if frame is None:
                return
            name = time.strftime("%m%d_%H%M%S") + f"_{self.debug_name}_{reason}.png"
            g.save_frame(paths.data(os.path.join("logs", name)), frame)
        except Exception:                               # noqa: BLE001
            pass


def ad_visible(game, frame=None):
    """畫面上看得到廣告關閉鈕。frame 不給就截一張（16:9 時看整個視窗）。"""
    c = AdCloser(game)
    if frame is None:
        frame = c.frames()[1]
    return c.visible(frame)
