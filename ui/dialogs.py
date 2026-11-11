# -*- coding: utf-8 -*-
"""小視窗：新增／複製項目、確認刪除。都是 modal（開著時不能操作主視窗）。"""
import tkinter as tk

import customtkinter as ctk

from .theme import C, F, L, M, S, XL, XS, RADIUS, Box, label, outline_button, primary_button

NAME_MAX = 20


def validate_name(name, existing, keep=None):
    """名稱規則（和主程式一致）：去空白後 1～20 字、不能有 / \\、同類型不重複。回傳 (名稱, 錯誤訊息)。"""
    n = (name or "").strip()
    if not n:
        return n, "請輸入名稱"
    if len(n) > NAME_MAX:
        return n, f"名稱最多 {NAME_MAX} 個字"
    if "/" in n or "\\" in n:
        return n, "名稱不能有 / 或 \\"
    if n != keep and n in set(existing):
        return n, f"「{n}」已經有了，請換一個名稱"
    return n, ""


def unique_name(base, existing):
    """「瑪歛克」→「瑪歛克 2」、「瑪歛克 3」…（不超過字數上限）。"""
    existing = set(existing)
    for k in range(2, 100):
        suffix = f" {k}"
        n = base[:NAME_MAX - len(suffix)] + suffix
        if n not in existing:
            return n
    return base[:NAME_MAX]


class Modal:
    """深色 modal 視窗的共同部分。"""

    def __init__(self, main, title, width=420):
        self.main = main
        self.closed = False
        root = main.root
        w = self.win = ctk.CTkToplevel(root, fg_color=C["bg"])
        w.title(title)
        w.resizable(False, False)
        w.transient(root)
        w.protocol("WM_DELETE_WINDOW", self.cancel)
        w.bind("<Escape>", lambda e: self.cancel())
        w.minsize(width, 120)
        self.body = Box(w, "bg")
        self.foot = Box(w, "panel")
        self.foot.pack(fill="x", side="bottom")
        Box(self.foot, "border", height=1).pack(fill="x", side="top")
        self.btns = Box(self.foot, "panel")
        self.btns.pack(fill="x", padx=XL, pady=M)
        self.body.pack(fill="both", expand=True, padx=XL, pady=(L + XS, L))
        main._modal = self

    def show(self, focus=None):
        w, root, sc = self.win, self.main.root, self.main.scale
        w.update_idletasks()
        ww = w.winfo_reqwidth() / sc
        x = root.winfo_rootx() / sc + (root.winfo_width() / sc - ww) / 2
        y = root.winfo_rooty() / sc + 100
        geo = f"+{int(max(0, x))}+{int(max(0, y))}"
        w.geometry(geo)
        w.after(120, lambda: w.winfo_exists() and w.geometry(geo))    # 有時視窗剛出現時位置會被重設
        w.lift()
        w.focus_force()
        w.after(150, lambda: self._grab(focus))

    def _grab(self, focus):
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        if focus is not None:
            focus.focus_set()

    def cancel(self):
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
        if getattr(self.main, "_modal", None) is self:
            self.main._modal = None


class ConfirmDialog(Modal):
    def __init__(self, main, title, message, ok_text, on_ok, danger=True):
        super().__init__(main, title, width=380)
        self.on_ok = on_ok
        label(self.body, message, F.body, anchor="w", justify="left", wraplength=340).pack(anchor="w")
        if danger:
            ok = ctk.CTkButton(self.btns, text=ok_text, command=self._ok, width=80, height=34, corner_radius=RADIUS,
                               fg_color="#8E2F2B", hover_color="#A83A35", text_color=C["white"], font=F.body_bold)
        else:
            ok = primary_button(self.btns, ok_text, self._ok, width=80, height=34)
        ok.pack(side="right")
        outline_button(self.btns, "取消", self.cancel, width=72, height=34, font=F.body_bold).pack(side="right", padx=(0, S))
        self.win.bind("<Return>", lambda e: self._ok())
        self.win.after(10, lambda: self.show(focus=ok))

    def _ok(self):
        self.close()
        self.on_ok()


class AddItemDialog(Modal):
    """
    新增（或複製）項目。
    groups      [(類型路徑, 顯示名稱)]
    items       {類型路徑: [項目路徑, ...]}
    on_submit   (類型路徑, 名稱, 複製來源路徑或 None) -> (ok, 訊息)
    """
    DEFAULT = "預設值"

    def __init__(self, main, groups, items, on_submit, group=None, copy_from=None, name=""):
        super().__init__(main, "複製項目" if copy_from else "新增項目")
        self.groups, self.items, self.on_submit = groups, items, on_submit
        self.group_by_name = {n: g for g, n in groups}
        b = self.body
        b.grid_columnconfigure(1, weight=1)
        group = group if group in dict(groups) else groups[0][0]

        label(b, "名稱", F.body).grid(row=0, column=0, sticky="w", pady=(0, S))
        self.name_var = tk.StringVar(value=name)
        self.entry = ctk.CTkEntry(b, textvariable=self.name_var, height=34, corner_radius=RADIUS, font=F.body,
                                  fg_color=C["input"], border_color=C["border"], border_width=1,
                                  text_color=C["text"], width=260)
        self.entry.grid(row=0, column=1, sticky="ew", padx=(M, 0), pady=(0, S))
        self.err = label(b, "", F.small, "err", anchor="w")
        self.err.grid(row=1, column=1, sticky="w", padx=(M, 0))
        self.err.grid_remove()

        label(b, "放在", F.body).grid(row=2, column=0, sticky="w", pady=(0, S))
        self.group_var = tk.StringVar(value=dict(groups)[group])
        self.group_menu = self._option(b, [n for _, n in groups], self.group_var, self._group_changed)
        self.group_menu.grid(row=2, column=1, sticky="ew", padx=(M, 0), pady=(0, S))

        label(b, "設定", F.body).grid(row=3, column=0, sticky="w")
        self.copy_var = tk.StringVar(value=self.DEFAULT)
        self.copy_menu = self._option(b, [self.DEFAULT], self.copy_var, lambda _: None)
        self.copy_menu.grid(row=3, column=1, sticky="ew", padx=(M, 0))
        label(b, "可以從預設值開始，或複製同類型某個項目的全部設定（包括還沒按開始的修改）。\n"
                 "建好之後會自動選取，可以馬上修改出招流程。", F.small, "sub", anchor="w", justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(M, 0))

        self.ok_btn = primary_button(self.btns, "新增", self._ok, width=80, height=34)
        self.ok_btn.pack(side="right")
        outline_button(self.btns, "取消", self.cancel, width=72, height=34, font=F.body_bold).pack(side="right", padx=(0, S))

        self._group_changed(self.group_var.get(), keep_copy=copy_from)
        self.name_var.trace_add("write", lambda *_: self._check())
        self.win.bind("<Return>", lambda e: self._ok())
        self._check(show=False)
        self.win.after(10, lambda: self.show(focus=self.entry))
        self.win.after(200, lambda: self.entry.select_range(0, "end"))

    def _option(self, master, values, var, command):
        return ctk.CTkOptionMenu(master, values=values, variable=var, height=34, corner_radius=RADIUS,
                                 font=F.body, dropdown_font=F.body, fg_color=C["input"], button_color=C["input"],
                                 button_hover_color=C["input_hover"], text_color=C["text"],
                                 dropdown_fg_color=C["panel"], dropdown_hover_color=C["accent"],
                                 dropdown_text_color=C["text"], dynamic_resizing=False, command=command)

    def _group(self):
        return self.group_by_name[self.group_var.get()]

    def _group_changed(self, _name, keep_copy=None):
        paths = self.items.get(self._group(), [])
        self.copy_paths = {f"複製「{p[-1]}」": p for p in paths}
        self.copy_menu.configure(values=[self.DEFAULT] + list(self.copy_paths))
        want = next((k for k, p in self.copy_paths.items() if p == keep_copy), None)
        self.copy_var.set(want or self.DEFAULT)
        self._check()

    def _check(self, show=True):
        names = [p[-1] for p in self.items.get(self._group(), [])]
        _, err = validate_name(self.name_var.get(), names)
        if err and show and self.name_var.get().strip():
            self._error(err)
        else:
            self.err.grid_remove()
        ok = not err
        self.ok_btn.configure(state="normal" if ok else "disabled", fg_color=C["accent"] if ok else C["accent_dim"])
        self.entry.configure(border_color=C["err"] if (err and show and self.name_var.get().strip()) else C["border"])
        return ok

    def _error(self, msg):
        self.err.configure(text=msg)
        self.err.grid()

    def _ok(self):
        if not self._check():
            return
        src = self.copy_paths.get(self.copy_var.get())
        ok, msg = self.on_submit(self._group(), self.name_var.get(), src)
        if ok:
            self.close()
        else:
            self._error(msg or "新增失敗")
