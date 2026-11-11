# -*- coding: utf-8 -*-
"""開發測試用任務（釣魚、戰鬥還沒做好時自動出現；設定 show_demo_tasks 或 --demo 也會出現）。"""
from core.task import Param, Task


class ClickTest(Task):
    path = ("開發測試", "背景點擊")
    description = "每隔幾秒在指定位置點一下，測試背景執行、停止、熱鍵。請選一個點了不會有損失的位置。"
    params = [
        Param("x", "X 位置（比例）", float, default=0.5, min=0.0, max=1.0, help="0 = 最左、1 = 最右"),
        Param("y", "Y 位置（比例）", float, default=0.5, min=0.0, max=1.0, help="0 = 最上、1 = 最下"),
        Param("count", "點擊次數", int, default=5, min=1, max=1000),
        Param("interval", "間隔（秒）", float, default=2.0, min=0.2, max=60),
    ]

    def run(self):
        n = self.values["count"]
        for i in range(n):
            if self.should_stop():
                return
            self.set_progress(f"第 {i + 1}/{n} 次")
            self.game.click(self.values["x"], self.values["y"])
            self.log(f"點擊 ({self.values['x']:.2f}, {self.values['y']:.2f})，第 {i + 1}/{n} 次")
            if not self.sleep(self.values["interval"]):
                return


class CountTest(Task):
    path = ("開發測試", "計數（不操作遊戲）")
    description = "只會數數字、不碰遊戲，測試介面、進度、停止。"
    params = [
        Param("seconds", "秒數", int, default=10, min=1, max=3600),
        Param("fail", "最後故意出錯", bool, default=False, help="測試錯誤處理：程式不能當掉"),
        Param("mode", "模式", str, default="一般", choices=["一般", "快速"]),
    ]

    def run(self):
        step = 0.2 if self.values["mode"] == "快速" else 1.0
        total = int(self.values["seconds"] / step)
        for i in range(total):
            self.set_progress(f"{i + 1}/{total}")
            if i % max(1, int(1 / step)) == 0:
                self.log(f"計數 {i + 1}/{total}")
            if not self.sleep(step):
                return
        if self.values["fail"]:
            raise RuntimeError("這是故意的測試錯誤")


class AdTest(Task):
    path = ("開發測試", "關廣告測試")
    description = ("畫面上有廣告時按開始：只用 core 的關廣告處理（略過／✕、移除廣告高級版、卡住按喇叭、Shift+Tab），"
                   "不會做其他事（不會自動走路、不會釣魚）。廣告關掉後會一直待命，按 F6 停止。")
    params = [
        Param("seconds", "最多幾秒", int, default=120, min=10, max=600, help="時間到自動停止"),
    ]

    def run(self):
        from core.ads import AdCloser
        ads = AdCloser(self.game, log=self.log, debug_name="關廣告測試")
        gf, af = ads.frames()
        mode = "16:9（遊戲畫面＋整個視窗都找）" if self.game.letterboxed else "9:16（只找遊戲畫面）"
        self.log(f"🧪 關廣告測試開始，視窗：{mode}")
        hit = ads.find_close(af)
        sp = ads.speaker(gf, af)
        self.log("   現在畫面：" + (f"看得到「{hit[0].replace('廣告_', '')}」" if hit else "沒有認得的關閉鈕")
                 + ("、看得到喇叭" if sp else ""))
        # done 永遠是 False：完整跑一遍（按鈕、喇叭、Shift+Tab），直到時間到或按 F6
        ads.close_until(done=lambda f: False, timeout=self.values["seconds"], debug_on_timeout=None)
        if not self.should_stop():
            ads.save_debug("測試結束畫面")
            self.log("🧪 時間到。最後的畫面存在 logs 資料夾")


TASKS = [ClickTest, CountTest, AdTest]
