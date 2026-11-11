# -*- coding: utf-8 -*-
"""
戰鬥類型（範本）。功能樹：戰鬥 › 類型 › 使用者自己建的項目。

    combat.TEMPLATES = [Raid, GuildBoss]

主程式為每個項目動態產生子類別（`make_item()`），path = group + (項目名稱,)。
新增類型：在這裡加一個類別、放進 TEMPLATES，template_id 定了之後不要改（設定檔用）。
規格見 02_Tkinter外型.md「📝 提案：自訂戰鬥項目」。
"""
import dataclasses
import time

from core.task import Param

from .raid.common import BattleTask


class Raid(BattleTask):
    template_id = "raid"
    group = ("戰鬥", "討伐戰")
    type_name = "討伐戰"
    description = "討伐戰：照自訂的出招流程打一場，打完就停。"
    uses_stamina = True           # 打別人開的王要 ⚡10（房主不用）
    can_minimize = True           # 練習模式沒有最小化按鈕，執行時會自動改成留在畫面
    default_items = [
        ("瑪歛克", {"sequence": "技能1 > 自動"}),
        ("泰迪布羅", {"sequence": "技能1 > 替換2 > 必殺技 > 替換3 > 必殺技 > 自動"}),
    ]


Raid.params = Raid.make_params(refill=(True, True, False))     # 使用者決定：看廣告 ✅、恢復劑 ✅、鑽石 ❌


class GuildBoss(BattleTask):
    """
    公會BOSS（遊戲裡叫「公會戰役」）：一天挑戰一次，另外可以無限練習。不花體力、戰鬥畫面沒有最小化。
    入口：村莊 → 選單 → 公會 → 公會戰役（使用者截圖 截圖/戰鬥/戰鬥_公會BOSS_1～6.png）
    從村莊、選單、公會、公會戰役畫面、隊伍確認或戰鬥中開始都可以（會自己走過去）；
    今天挑戰過了（灰色「挑戰完成」）→ 停止。
    ⚠ 正式挑戰的隊伍確認、打完的畫面還沒看過，先沿用討伐戰的判斷。
    """
    template_id = "guild_boss"
    group = ("戰鬥", "公會BOSS")
    type_name = "公會BOSS"
    description = "公會BOSS（公會戰役）：照自訂的出招流程打一場，打完就停。挑戰一天一次，練習不限。"
    uses_stamina = False
    can_minimize = False
    default_items = []

    CHALLENGE = "挑戰"
    PRACTICE = "練習"
    CHALLENGE_BTN = (0.50, 0.945)     # 公會戰役畫面中間的「挑戰」
    PRACTICE_BTN = (0.14, 0.945)      # 左下「練習」

    def _enter_extra(self, s, clicked):
        # 1. 公會戰役畫面：按「開始挑戰」或「練習」
        if s.find("guild_screen") or s.find("guild_start") or s.find("guild_done"):
            if not self.values["enter"]:
                self.log("❌ 目前在公會戰役畫面，請先進入戰鬥再開始（或勾選「從入口自動進場」）")
                return "stop"
            mode = self.values["mode"]
            if mode == self.CHALLENGE and s.find("guild_done"):
                self.log("❌ 公會BOSS 今天已經挑戰過了（挑戰完成）。要練習的話，把「模式」改成「練習」")
                return "stop"
            m = s.find("guild_start") if mode == self.CHALLENGE else s.find("guild_screen")
            pos = (m.x, m.y) if m else (self.CHALLENGE_BTN if mode == self.CHALLENGE else self.PRACTICE_BTN)
            return self._nav(clicked, "guild", f"按「{mode}」", lambda: self.game.click(*pos))

        if not self.values["enter"]:
            return None
        # 2. 公會畫面：「公會戰役」卡片露出來就點，不然往下捲
        card = s.find("guild_card")
        if card and card.y < 0.82:
            return self._nav(clicked, "card", "進入「公會戰役」", lambda: self.game.click(card.x, card.y))
        if card or s.find("guild_home"):
            return self._nav(clicked, "scroll", "往下捲，找「公會戰役」",
                             lambda: self.game.drag(0.5, 0.75, 0.5, 0.35, seconds=0.5), limit=5)
        # 3. 選單開著：按「公會」
        m = s.find("menu_guild")
        if m:
            return self._nav(clicked, "menu_guild", "按選單的「公會」", lambda: self.game.click(m.x, m.y))
        # 4. 村莊：按右下 ≡ 打開選單
        m = s.find("menu_btn_v") or s.find("menu_btn")
        if m:
            return self._nav(clicked, "menu", "打開選單", lambda: self.game.click(m.x, m.y))
        return None

    def _nav(self, clicked, key, text, action, limit=3):
        """同一個動作至少隔 3 秒，最多 limit 次；超過就停止。"""
        if time.monotonic() - clicked.get(key, 0) <= 3:
            return "clicked"
        n = clicked[key + "_n"] = clicked.get(key + "_n", 0) + 1
        if n > limit:
            self._debug("走到公會戰役卡住")
            self.log(f"❌ {text}試了 {limit} 次都沒反應，已停止。截圖存在 logs 資料夾。")
            return "stop"
        self.log(text)
        action()
        clicked[key] = time.monotonic()
        return "clicked"


GuildBoss.params = GuildBoss.make_params(refill=None)
GuildBoss.params.insert(1, Param(
    "mode", "模式", str, default=GuildBoss.CHALLENGE, choices=[GuildBoss.CHALLENGE, GuildBoss.PRACTICE],
    help="從公會戰役畫面開始時要按哪個：挑戰（一天一次）或練習（不限次數）"))

TEMPLATES = [Raid, GuildBoss]


def make_item(template, name, values=None):
    """
    產生一個項目的任務類別（主程式和 `python -m combat` 用）。
    values：這個項目自己的預設值（例：default_items 裡的出招流程），會蓋過類型的預設值。
    """
    attrs = {"path": tuple(template.group) + (name,), "__module__": template.__module__}
    if values:
        attrs["params"] = [dataclasses.replace(p, default=values[p.key]) if p.key in values else p
                           for p in template.params]
    return type(f"{template.__name__}_{name}", (template,), attrs)


def default_tasks():
    """所有類型的預設項目（主程式還沒支援 TEMPLATES 時的過渡用）。"""
    return [make_item(t, n, v) for t in TEMPLATES for n, v in t.default_items]
