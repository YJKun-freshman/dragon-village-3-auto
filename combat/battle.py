# -*- coding: utf-8 -*-
"""
戰鬥畫面的判斷與操作（回合制戰鬥，討伐戰以外的戰鬥之後也可以共用）。

座標都是正規化畫面（高度 1000）的比例，量自 2026-11-06 使用者的截圖（截圖/戰鬥/）。
"""

import cv2
import numpy as np

from core import vision

# ---- 找圖：畫面和樣板都先模糊（BLUR），1.0 倍找不到再試其他倍率（SCALES）
# 視窗大小／比例不同時清晰度不一樣（2026-11-07），16:9 時有些介面會放大 1.16～1.26 倍（2026-11-08）
# 用 core v0.5.0 的 find(..., scales=, blur=)（結果和戰鬥 v0.4.6 自己的版本完全一樣）
BLUR = 5
SCALES = (1.0, 1.08, 1.16, 1.26, 0.93)

T = "combat/templates/common/"

# ---- 按鈕位置（點擊用的中心點）
BTN = {
    "skill1": (0.155, 0.860),
    "skill2": (0.351, 0.860),
    "ult":    (0.583, 0.860),
    "attack": (0.861, 0.893),
    "swap":   (0.155, 0.673),
    "auto":   (0.522, 0.677),
}
# ---- 判斷按鈕亮／暗用的範圍（像素，正規化畫面 561×1000）
BTN_BOX = {
    "skill1": (40, 817, 130, 912),
    "skill2": (150, 817, 245, 912),
    "ult":    (275, 817, 370, 912),
    "attack": (420, 825, 545, 955),
}
READY_V = 85          # 按鈕平均亮度 > 這個 = 可以按（實測：可按 122～152，暗 22～48）
ATTACK_GLOW = 0.08    # 普攻按鈕橘色外框比例 > 這個 = 輪到我（實測：我方 0.14～0.23，其他 ≤ 0.02）

# ---- 替換視窗：隊伍 3 格，順序固定；目前上場那格按鈕是綠色
SWAP_SLOT_CLICK = {1: (0.905, 0.260), 2: (0.905, 0.485), 3: (0.905, 0.712)}
SWAP_SLOT_COLOR = {1: (505, 220), 2: (505, 445), 3: (505, 675)}    # 取色點（避開中間的白色圖示）

# ---- 「恢復活力」視窗的三張卡（看廣告／活力恢復劑／鑽石）：點擊位置、判斷能不能用的範圍
REFILL_CARD = {"ad": (0.21, 0.61), "potion": (0.50, 0.61), "gems": (0.79, 0.61)}
REFILL_CARD_BOX = {"ad": (45, 500, 190, 600), "potion": (210, 500, 355, 600), "gems": (372, 500, 520, 600)}
REFILL_READY_V = 200      # 卡片上半部平均亮度（實測：可用 239～240，今天用完變暗 146）
POTION_USE = (0.503, 0.600)   # 「使用活力恢復劑」視窗的「使用」按鈕（預設數量 1 個）

# ---- 剩餘回合數字的範圍（只判斷「有沒有變」，不讀數字）
ROUND_BOX = (490, 150, 535, 178)

# ---- 樣板與搜尋範圍
TPL = {
    "my_turn":  (T + "我方回合_請選擇.png", (0.02, 0.72, 0.85, 0.80), 0.88),   # 模糊後對方回合 0.82
    # 泰迪布羅 AUTO 在 x≈0.52；瑪歛克少一顆按鈕，AUTO 在 x≈0.63 → 範圍放寬，點的時候用找到的位置
    "auto_on":  (T + "AUTO_開.png", (0.40, 0.63, 0.80, 0.72), 0.80),
    "auto_off": (T + "AUTO_關.png", (0.40, 0.63, 0.80, 0.72), 0.80),
    "end":      (T + "戰鬥結束.png", (0.25, 0.07, 0.75, 0.24), 0.85),
    "confirm":  (T + "確認.png", (0.25, 0.85, 0.75, 0.99), 0.85),
    "forced_swap": (T + "強制替換_標題.png", (0.20, 0.08, 0.80, 0.18), 0.85),
    # 體力不足：按「戰鬥」後跳出「恢復活力」（看廣告／恢復劑／鑽石）；選恢復劑會再跳「使用活力恢復劑」
    "no_stamina": (T + "彈窗_恢復活力.png", (0.20, 0.38, 0.80, 0.54), 0.85),
    "potion":     (T + "彈窗_活力恢復劑.png", (0.20, 0.20, 0.80, 0.33), 0.85),
    "popup_x":    (T + "彈窗_恢復活力_X.png", (0.30, 0.60, 0.70, 0.90), 0.80),
    # 按「戰鬥」後可能跳出「有龍尚未裝備寶珠。要裝備嗎？」→ 按「繼續遊戲」（使用者決定）
    "no_gem":     (T + "彈窗_未裝備寶珠.png", (0.15, 0.45, 0.85, 0.62), 0.85),
    "no_gem_go":  (T + "彈窗_繼續遊戲.png", (0.10, 0.55, 0.55, 0.72), 0.85),
    # 練習打完回到「請選擇要練習的討伐戰」清單（使用者截圖 23:14）
    "practice_list": (T + "練習_選擇討伐戰.png", (0.15, 0.07, 0.85, 0.18), 0.85),
    # 公會戰役畫面（公會 → 公會戰役）：左下「練習」、中間「挑戰」（今天打過會變灰色「挑戰完成」）
    "guild_screen": (T + "公會戰役_練習.png", (0.00, 0.85, 0.30, 1.00), 0.75),   # 16:9 時 0.86，其他畫面 ≤ 0.40
    # 從村莊走到公會戰役：村莊右下 ≡ → 選單「公會」→ 公會畫面往下捲 →「公會戰役」卡片
    "menu_btn":     (T + "選單按鈕.png", (0.80, 0.78, 1.00, 0.95), 0.90),          # 選單開著時的 ≡
    "menu_btn_v":   (T + "選單按鈕_村莊.png", (0.80, 0.78, 1.00, 0.95), 0.90),     # 村莊的 ≡（有紅點、綠底）
    "menu_guild":   (T + "選單_公會.png", (0.00, 0.30, 1.00, 0.75), 0.85),
    "guild_home":   (T + "公會_標題.png", (0.00, 0.00, 0.20, 0.08), 0.90),
    "guild_card":   (T + "公會_公會戰役.png", (0.00, 0.10, 0.50, 0.95), 0.85),
    "guild_start":  (T + "公會戰役_開始挑戰.png", (0.25, 0.85, 0.75, 1.00), 0.85),  # 「開始挑戰！每日 1/1次」
    "guild_done":   (T + "公會戰役_挑戰完成.png", (0.25, 0.85, 0.75, 1.00), 0.85),
    # 討伐戰巡迴：村莊 → 羅盤 → 探險 →「討伐戰」卡片 → 討伐戰清單（參與前）
    "compass":      (T + "村莊_羅盤.png", (0.35, 0.88, 0.65, 1.00), 0.90),
    "compass_go":   (T + "羅盤_探險.png", (0.15, 0.75, 0.45, 0.95), 0.85),
    "explore_raid": (T + "探險_討伐戰.png", (0.00, 0.30, 0.50, 0.90), 0.85),
    "explore_busy": (T + "探險_委託戰鬥中.png", (0.20, 0.30, 0.80, 0.90), 0.85),   # 最小化的戰鬥還沒打完
    "raid_title":   (T + "討伐戰清單_標題.png", (0.00, 0.00, 0.25, 0.08), 0.90),    # 隊伍確認的標題也會對到
    "raid_list":    (T + "討伐戰清單_參與前.png", (0.15, 0.10, 0.55, 0.22), 0.85),  # 「參與前」分頁（選中＝黃色）
    "close_br":     (T + "右下X.png", (0.80, 0.85, 1.00, 1.00), 0.90),
    "swap_x":   (T + "替換_關閉X.png", (0.35, 0.80, 0.65, 0.96), 0.85),
    "prepare":  (T + "戰鬥準備.png", (0.20, 0.85, 0.80, 0.99), 0.85),
    "start":    (T + "戰鬥_開始.png", (0.20, 0.85, 0.80, 0.99), 0.85),          # 按鈕下方有 ⚡10（泰迪布羅正式）
    # 正式模式才有（練習、公會 BOSS 沒有）；按了戰鬥會縮到背景，回到村莊
    "minimize": (T + "最小化.png", (0.70, 0.63, 0.92, 0.72), 0.85),
    # 縮到背景後，村莊下方那排字（打完會變成別的字）
    "bg_fighting": (T + "村莊_首領交戰中.png", (0.10, 0.80, 0.90, 0.92), 0.85),
    "start_practice": (T + "戰鬥_開始_練習.png", (0.20, 0.85, 0.80, 0.99), 0.85),  # 按鈕沒有體力費用（練習，或自己是房主的正式場）
}


def _px(frame, box):
    """像素範圍（以 561×1000 量的）→ 依實際寬度換算後裁切。"""
    h, w = frame.shape[:2]
    sx, sy = w / 561.0, h / 1000.0
    x0, y0, x1, y1 = box
    return frame[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)]


class Screen:
    """一張截圖的判斷結果（每次截圖建一個，避免重複找圖）。"""

    def __init__(self, game, frame=None):
        self.game = game
        self.frame = game.capture() if frame is None else frame
        self._cache = {}

    def find(self, key):
        if key not in self._cache:
            path, region, thr = TPL[key]
            self._cache[key] = vision.find(self.frame, path, region, thr, scales=SCALES, blur=BLUR)
        return self._cache[key]

    def score(self, key):
        path, region, _ = TPL[key]
        return vision.best_score(self.frame, path, region, scales=SCALES, blur=BLUR)

    # ---- 狀態
    @property
    def in_battle(self):
        return bool(self.find("auto_on") or self.find("auto_off"))

    def auto_pos(self):
        """AUTO 按鈕的位置（比例），找不到用預設位置。"""
        m = self.find("auto_on") or self.find("auto_off")
        return (m.x, m.y) if m else BTN["auto"]

    @property
    def auto_on(self):
        """AUTO 是否開著（None = 看不到 AUTO 按鈕）。"""
        if not self.in_battle:
            return None
        return self.score("auto_on") > self.score("auto_off")

    def attack_glow(self):
        hsv = cv2.cvtColor(_px(self.frame, BTN_BOX["attack"]), cv2.COLOR_BGR2HSV)
        m = (hsv[..., 0] >= 5) & (hsv[..., 0] <= 30) & (hsv[..., 1] > 120) & (hsv[..., 2] > 200)
        return float(m.mean())

    @property
    def my_turn(self):
        """輪到我選行動：有「請選擇…的下一個行動」而且普攻按鈕是亮的。
        （原本看普攻的橘色外框，但瑪歛克的場景外框比較淡：0.035，改看亮度）"""
        return bool(self.find("my_turn")) and self.ready("attack")

    def ready(self, action):
        """技能按鈕是不是亮的（寶珠夠、沒冷卻）。"""
        if action not in BTN_BOX:
            return True
        return float(cv2.cvtColor(_px(self.frame, BTN_BOX[action]), cv2.COLOR_BGR2HSV)[..., 2].mean()) > READY_V

    @property
    def outside(self):
        """回到戰鬥外的畫面：隊伍確認、討伐戰入口（練習模式打完會直接回到這裡）。"""
        return bool(self.find("start") or self.find("start_practice") or self.find("prepare")
                    or self.find("practice_list") or self.find("guild_screen") or self.find("raid_list"))

    @property
    def ended(self):
        return bool(self.find("end"))

    @property
    def swap_open(self):
        return bool(self.find("swap_x"))

    def slot_state(self, slot):
        """替換視窗中第 slot 格：'可換'（紫）、'上場中'（綠）、'不能換'（灰，已倒下）、None（看不出來）。"""
        x, y = SWAP_SLOT_COLOR[slot]
        b, g, r = (int(v) for v in _px(self.frame, (x - 4, y - 4, x + 4, y + 4)).reshape(-1, 3).mean(0))
        if b > 180 and g < 140 and r > 120:
            return "可換"
        if g > b + 40 and g > r + 40:
            return "上場中"
        if max(b, g, r) - min(b, g, r) < 20:
            return "不能換"
        return None

    def refill_ready(self, kind):
        """恢復活力視窗中，這張卡今天還能不能用（用完會變暗）。"""
        v = cv2.cvtColor(_px(self.frame, REFILL_CARD_BOX[kind]), cv2.COLOR_BGR2HSV)[..., 2].mean()
        return float(v) > REFILL_READY_V

    @property
    def forced_swap(self):
        """角色倒下後的「請選擇要替換的龍」（沒有 X，一定要選一隻）。"""
        return bool(self.find("forced_swap"))

    def round_mask(self):
        """剩餘回合數字的白色像素（判斷回合有沒有變用）。"""
        roi = _px(self.frame, ROUND_BOX)
        m = (roi.min(axis=2) > 200).astype(np.uint8)
        return cv2.resize(m, (45, 28), interpolation=cv2.INTER_NEAREST)

    def name(self):
        """給日誌看的目前畫面名稱。"""
        if self.ended:
            return "戰鬥結束"
        if self.find("no_stamina") or self.find("potion"):
            return "恢復活力彈窗（體力不足）"
        if self.find("raid_list"):
            return "討伐戰清單"
        if self.find("explore_raid"):
            return "探險"
        if self.find("practice_list"):
            return "練習選單"
        if self.find("guild_screen"):
            return "公會戰役"
        if self.find("no_gem"):
            return "未裝備寶珠提示"
        if self.forced_swap:
            return "替換視窗（角色倒下）"
        if self.swap_open:
            return "替換視窗"
        if self.in_battle:
            return "戰鬥中（我方回合）" if self.my_turn else "戰鬥中"
        if self.find("bg_fighting"):
            return "村莊（首領戰在背景進行）"
        if self.find("start") or self.find("start_practice"):
            return "隊伍確認"
        if self.find("prepare"):
            return "討伐戰入口"
        return "不認得的畫面"


def round_changed(a, b, min_diff=0.06):
    """兩次的剩餘回合數字遮罩差多少（比例），> min_diff 視為數字變了。"""
    if a is None or b is None:
        return False
    union = np.count_nonzero(a | b)
    if union == 0:
        return False
    return np.count_nonzero(a ^ b) / union > min_diff
