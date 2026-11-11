# -*- coding: utf-8 -*-
"""
出招流程編輯器（Param 有 widget="sequence" 時使用）。

- 畫面是步驟清單，值仍然是文字（例：「技能1 > 替換2 > 必殺技 > 自動」），存設定檔、傳給任務都不變
- 文字 ↔ 清單、檢查都用主程式傳進來的 sequence_tools（來自 combat.sequence）：
      {"parse": 文字→清單, "to_text": 清單→文字, "validate": 檢查（有錯 raise，訊息是中文）}
- 步驟資料格式（combat.sequence 定的）：
      {"action": "skill1"} {"action": "skill2"} {"action": "ult"} {"action": "attack"}
      {"action": "swap", "slot": 2} {"action": "auto", "rounds": 0} {"action": "goto", "step": 3}
"""
import tkinter as tk

import customtkinter as ctk

from .theme import C, F, M, S, XS, RADIUS, Box, chip_button, label, menu_style
from .widgets import Field, Tooltip, help_icon

NAMES = {"skill1": "技能1", "skill2": "技能2", "ult": "必殺技", "attack": "普攻",
         "swap": "替換", "auto": "自動", "goto": "回到"}

HELP = ("從上到下依序執行。技能、必殺技、普攻、替換各用掉一回合。\n"
        "點一步選取它，新加入的步驟會插在它後面；選取的步驟可以上移、下移、刪除。\n"
        "「自動」會一直打到戰鬥結束，所以要放最後；中途想切回手動請用「自動 N 回合」。\n"
        "「回到第 N 步」可以做循環。")


def describe(s):
    """(主要文字, 補充說明)"""
    a = s.get("action")
    if a == "swap":
        return "替換", f"→ 第 {s.get('slot')} 隻"
    if a == "auto":
        r = int(s.get("rounds") or 0)
        return ("自動", f"{r} 回合後切回手動") if r else ("自動", "打到戰鬥結束")
    if a == "goto":
        return "回到", f"第 {s.get('step')} 步（循環）"
    return NAMES.get(a, str(a)), ""



class SequenceEditor(Field):
    def __init__(self, master, p, value, on_change, tools, scale=1.0):
        self.p, self.tools, self.on_change, self.scale = p, tools, on_change, scale
        self.enabled = True
        self.sel = None              # 選取的步驟 index（0 起算）；None = 插到最後
        self.load_error = ""
        self.steps = self._parse_initial(value)

        w = self.widget = Box(master, "panel")
        w.grid_columnconfigure(0, weight=1)

        head = Box(w, "panel")
        head.grid(row=0, column=0, sticky="ew", pady=(0, S))
        label(head, p["label"], F.section, "sub").pack(side="left")
        help_icon(head, HELP).pack(side="left", padx=(6, 0))
        self.count_lbl = label(head, "", F.small, "sub")
        self.count_lbl.pack(side="right")

        self.box = ctk.CTkFrame(w, fg_color=C["list_bg"], border_color=C["border"], border_width=1,
                                corner_radius=8)
        self.box.grid(row=1, column=0, sticky="ew")
        self.box.grid_columnconfigure(0, weight=1)

        pal = Box(w, "panel")
        pal.grid(row=2, column=0, sticky="ew", pady=(M, 0))
        self.where_lbl = label(pal, "", F.small, "sub", anchor="w")
        self.where_lbl.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, XS))
        for c in range(4):
            pal.grid_columnconfigure(c, weight=1, uniform="pal")
        add = lambda step: (lambda: self.insert(dict(step)))
        self.pal_btns = [
            chip_button(pal, "技能1", add({"action": "skill1"})),
            chip_button(pal, "技能2", add({"action": "skill2"})),
            chip_button(pal, "必殺技", add({"action": "ult"})),
            chip_button(pal, "普攻", add({"action": "attack"})),
            chip_button(pal, "替換 ▾", None),
            chip_button(pal, "自動", add({"action": "auto", "rounds": 0})),
            chip_button(pal, "自動N回合 ▾", None),
            chip_button(pal, "回到第N步 ▾", None),
        ]
        b = self.pal_btns
        b[4].configure(command=lambda: self._menu(b[4], self._swap_items()))
        b[6].configure(command=lambda: self._menu(b[6], self._auto_items()))
        b[7].configure(command=lambda: self._menu(b[7], self._goto_items()))
        Tooltip(b[6], "開自動 N 回合後關掉自動，繼續下一步（實驗功能）")
        Tooltip(b[7], "跳回前面的某一步，用來做循環")
        for i, btn in enumerate(b):
            btn.grid(row=1 + i // 4, column=i % 4, sticky="ew", padx=(0 if i % 4 == 0 else XS, 0), pady=(0, XS))

        self.msg = label(w, "", F.small, "ok", anchor="w", justify="left")
        self.msg.grid(row=3, column=0, sticky="ew", pady=(XS, 0))
        self._wrap = 0
        w.bind("<Configure>", self._on_resize, add="+")     # 用外框寬度算換行（用標籤自己的寬度會來回跳動）
        self._rebuild()

    def _on_resize(self, e):
        wrap = max(120, int(e.width / self.scale) - 8)
        if abs(wrap - self._wrap) > 4:
            self._wrap = wrap
            self.msg.configure(wraplength=wrap)

    # ------------------------------------------------------------ 資料
    def _parse_initial(self, text):
        if not self.tools:
            return []
        try:
            return list(self.tools["parse"](text or ""))
        except Exception as e:
            self.load_error = f"設定檔裡的流程有錯（{e}），已改用預設流程"
            try:
                return list(self.tools["parse"](self.p.get("default") or ""))
            except Exception:
                return []

    def raw(self):
        try:
            return self.tools["to_text"](self.steps) if self.steps else ""
        except Exception:
            return ""

    def error(self):
        if not self.steps:
            return "出招流程是空的，請從下面加入步驟"
        try:
            self.tools["validate"](self.steps)
        except Exception as e:
            return str(e)
        return ""

    def value(self):
        msg = self.error()
        return (None, msg) if msg else (self.raw(), "")

    def summary(self):
        return f"流程 {len(self.steps)} 步"

    # ------------------------------------------------------------ 編輯
    def _renumber(self, mapping):
        """步驟搬動後，修正「回到第 N 步」指向的位置。mapping：舊 index → 新 index（被刪掉的不在裡面）。"""
        for s in self.steps:
            if s.get("action") == "goto":
                old = s.get("step", 1) - 1
                if old in mapping:
                    s["step"] = mapping[old] + 1

    def insert(self, step):
        if not self.enabled:
            return
        pos = len(self.steps) if self.sel is None else self.sel + 1
        n = len(self.steps)
        mapping = {i: (i if i < pos else i + 1) for i in range(n)}
        self._renumber(mapping)
        self.steps.insert(pos, step)
        self.sel = pos
        self._changed()

    def move(self, i, d):
        j = i + d
        if not self.enabled or not (0 <= j < len(self.steps)):
            return
        mapping = {k: k for k in range(len(self.steps))}
        mapping[i], mapping[j] = j, i
        self._renumber(mapping)
        self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
        self.sel = j
        self._changed()

    def delete(self, i):
        if not self.enabled:
            return
        mapping = {k: (k if k < i else k - 1) for k in range(len(self.steps)) if k != i}
        self._renumber(mapping)
        del self.steps[i]
        self.sel = (i - 1 if i > 0 else (0 if self.steps else None)) if self.steps else None
        self._changed()

    def select(self, i):
        if not self.enabled:
            return
        self.sel = None if self.sel == i else i      # 再點一次取消選取 → 插到最後
        self._rebuild()

    def _changed(self):
        self.load_error = ""
        self._rebuild()
        self.on_change()

    # ------------------------------------------------------------ 選單
    def _swap_items(self):
        return [(f"換成第 {k} 隻", lambda k=k: self.insert({"action": "swap", "slot": k})) for k in (1, 2, 3)]

    def _auto_items(self):
        items = [(f"{k} 回合", lambda k=k: self.insert({"action": "auto", "rounds": k})) for k in (3, 5, 10)]
        return items + [None, ("自訂回合數…", self._ask_rounds)]

    def _goto_items(self):
        pos = len(self.steps) if self.sel is None else self.sel + 1     # 新步驟會是第 pos+1 步
        if pos == 0:
            return [("（前面還沒有步驟）", None)]
        out = []
        for k in range(pos):
            main, sub = describe(self.steps[k])
            out.append((f"第 {k + 1} 步：{main}{(' ' + sub) if sub else ''}",
                        lambda k=k: self.insert({"action": "goto", "step": k + 1})))
        return out

    def _ask_rounds(self):
        d = ctk.CTkInputDialog(title="自動 N 回合", text="開自動幾回合後切回手動？（1～99）",
                               fg_color=C["panel"], button_fg_color=C["accent"],
                               button_hover_color=C["accent_hover"], entry_fg_color=C["input"],
                               entry_border_color=C["border"], font=F.body)
        s = (d.get_input() or "").strip()
        if s.isdigit() and 1 <= int(s) <= 99:
            self.insert({"action": "auto", "rounds": int(s)})

    def _menu(self, btn, items):
        if not self.enabled:
            return
        m = tk.Menu(btn, **menu_style(self.scale))
        for it in items:
            if it is None:
                m.add_separator()
            else:
                text, cmd = it
                m.add_command(label=text, command=cmd, state="normal" if cmd else "disabled")
        x, y = btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height() + 2
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # ------------------------------------------------------------ 畫面
    def _rebuild(self):
        for child in self.box.winfo_children():
            child.destroy()
        if not self.steps:
            label(self.box, "還沒有步驟，從下面的按鈕加入", F.small, "sub").grid(
                row=0, column=0, sticky="w", padx=M, pady=M)
        row = 0
        for i, s in enumerate(self.steps):
            last = i == len(self.steps) - 1 and i != self.sel
            self._row(i, s).grid(row=row, column=0, sticky="ew", padx=XS + 1,
                                 pady=(XS + 1 if i == 0 else 1, XS + 1 if last else 1))
            row += 1
            if i == self.sel:
                line = Box(self.box, "accent", height=2)
                line.grid(row=row, column=0, sticky="ew", padx=M,
                          pady=(1, XS + 1 if i == len(self.steps) - 1 else 1))
                row += 1

        n = len(self.steps)
        self.count_lbl.configure(text=f"共 {n} 步" if n else "")
        if self.sel is None:
            self.where_lbl.configure(text="加到最後：" if n else "加入第一步：")
        else:
            self.where_lbl.configure(text=f"插入到第 {self.sel + 1} 步後：")

        msg = self.load_error or self.error()
        if msg:
            self.msg.configure(text=msg, text_color=C["warn"] if self.load_error else C["err"])
        else:
            self.msg.configure(text=f"✓ 流程正確，共 {n} 步", text_color=C["ok"])
        self.box.configure(border_color=C["err"] if (msg and not self.load_error) else C["border"])

    def _row(self, i, s):
        on = i == self.sel
        # 只有選取的那列需要圓角底色，其他列用 Box（不用重畫）
        r = ctk.CTkFrame(self.box, fg_color=C["sel"], corner_radius=RADIUS, height=34) if on else Box(self.box, "list_bg")
        r.grid_columnconfigure(2, weight=1)
        badge = ctk.CTkLabel(r, text=str(i + 1), width=22, height=22, corner_radius=11,
                             fg_color=C["accent"] if on else C["input"],
                             text_color=C["white"] if on else C["sub"], font=F.tiny)
        badge.grid(row=0, column=0, padx=(S, S), pady=6)
        main, sub = describe(s)
        m = label(r, main, F.body_bold if on else F.body, "accent_text" if on else "text")
        m.grid(row=0, column=1, sticky="w")
        sl = label(r, sub, F.small, "sub")
        sl.grid(row=0, column=2, sticky="w", padx=(S, 0))
        for wdg in (r, badge, m, sl):
            wdg.bind("<Button-1>", lambda e, i=i: self.select(i))
        if on and self.enabled:
            acts = Box(r, "sel")
            acts.grid(row=0, column=3, padx=(0, S))
            mk = lambda t, cmd, ok=True, tip="": self._act(acts, t, cmd, ok, tip)
            mk("↑", lambda: self.move(i, -1), i > 0, "上移").pack(side="left", padx=(0, XS))
            mk("↓", lambda: self.move(i, 1), i < len(self.steps) - 1, "下移").pack(side="left", padx=(0, XS))
            mk("✕", lambda: self.delete(i), True, "刪除").pack(side="left")
        return r

    def _act(self, master, text, cmd, ok, tip):
        b = ctk.CTkButton(master, text=text, width=26, height=24, corner_radius=5, command=cmd,
                          fg_color="transparent", hover_color=C["input_hover"], border_width=1,
                          border_color=C["border"], text_color=C["sub"], text_color_disabled=C["faint"],
                          font=F.small, state="normal" if ok else "disabled")
        Tooltip(b, tip)
        return b

    # ------------------------------------------------------------ Field 介面
    def set_enabled(self, on):
        self.enabled = on
        for b in self.pal_btns:
            b.configure(state="normal" if on else "disabled")
        self._rebuild()

    def show_error(self, on):
        pass                              # 錯誤顯示在編輯器自己的訊息列

    def focus(self):
        self.box.focus_set()
