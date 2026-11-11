# -*- coding: utf-8 -*-
"""共用小元件：說明提示、數字欄、參數表單、功能樹、日誌。"""
import datetime
import re
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from .theme import C, F, M, S, XS, RADIUS, Box, label, px


# ================================================================== 說明提示（tooltip）
class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = self.job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _enter(self, _=None):
        self._cancel()
        self.job = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        self.job = None
        if self.tip or not self.text:
            return
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.configure(bg=C["border"])
        try:
            tw.attributes("-topmost", True)
        except tk.TclError:
            pass
        inner = ctk.CTkFrame(tw, fg_color="#333333", corner_radius=0)
        inner.pack(padx=1, pady=1)
        ctk.CTkLabel(inner, text=self.text, font=F.small, text_color=C["text"], justify="left",
                     anchor="w", wraplength=320).pack(padx=10, pady=6)
        tw.update_idletasks()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        sw = self.widget.winfo_screenwidth()
        x = max(0, min(x, sw - tw.winfo_reqwidth() - 8))
        tw.geometry(f"+{x}+{y}")
        self.tip = tw

    def _hide(self, _=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def help_icon(master, text):
    """標籤旁邊的 ? 圖示，滑鼠移上去顯示說明。"""
    w = ctk.CTkLabel(master, text="?", width=16, height=16, corner_radius=8, fg_color=C["input"],
                     text_color=C["sub"], font=F.tiny)
    Tooltip(w, text)
    return w


# ================================================================== 參數欄位
def _fmt_num(v, decimals):
    return str(int(v)) if decimals == 0 else f"{float(v):.{decimals}f}"


def _fmt_limit(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def _decimals(x):
    s = repr(float(x)).rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


class Field:
    """所有參數欄位的共同介面。"""
    widget = None

    def raw(self):              # 目前畫面上的內容（存草稿用）
        raise NotImplementedError

    def value(self):            # (值, 錯誤訊息)；沒錯時錯誤訊息是 ""
        raise NotImplementedError

    def set_enabled(self, on):
        pass

    def show_error(self, on):
        pass

    def focus(self):
        try:
            self.widget.focus_set()
        except Exception:
            pass


class NumberField(Field):
    """整數／小數：輸入框 + ▲▼。"""

    def __init__(self, master, p, value, on_change):
        self.p = p
        self.is_int = p["type"] is int
        lo, hi = p.get("min"), p.get("max")
        if self.is_int:
            self.step, self.dec = 1, 0
        else:
            span = (hi - lo) if (lo is not None and hi is not None) else 10
            self.step = 0.01 if span <= 1 else 0.1 if span <= 20 else 1.0
            self.dec = max(_decimals(self.step), _decimals(p.get("default") or 0), 1)
        self.err = False
        self.focused = False

        f = self.widget = ctk.CTkFrame(master, fg_color=C["input"], border_color=C["border"],
                                       border_width=1, corner_radius=RADIUS, height=32)
        self.var = tk.StringVar(value=self._display(value))
        self.entry = ctk.CTkEntry(f, textvariable=self.var, fg_color=C["input"], border_width=0,
                                  text_color=C["text"], font=F.body, height=26, corner_radius=4)
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=3)
        arrows = Box(f, "input")
        arrows.pack(side="right", padx=(0, 6), pady=3)
        self.up, self.down = self._arrow(arrows, "▲", 1), self._arrow(arrows, "▼", -1)
        self.up.pack()
        self.down.pack()
        self.enabled = True
        self.entry.bind("<Up>", lambda e: self.bump(1))
        self.entry.bind("<Down>", lambda e: self.bump(-1))
        self.entry.bind("<FocusIn>", lambda e: self._focus(True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._focus(False), add="+")
        self.var.trace_add("write", lambda *_: on_change())

    def _arrow(self, master, text, d):
        """小箭頭用 CTkLabel 做（CTkButton 最小高度太高）。"""
        a = ctk.CTkLabel(master, text=text, width=18, height=12, font=F.arrow, text_color=C["sub"],
                         corner_radius=3, fg_color="transparent")
        a.bind("<Button-1>", lambda e: self.bump(d))
        a.bind("<Enter>", lambda e: self.enabled and a.configure(fg_color=C["input_hover"], text_color=C["text"]))
        a.bind("<Leave>", lambda e: a.configure(fg_color="transparent", text_color=C["sub"] if self.enabled else C["faint"]))
        return a

    def _display(self, v):
        try:
            return _fmt_num(self.p["type"](v), self.dec)
        except (TypeError, ValueError):
            return str(v)

    def bump(self, d):
        if not self.enabled:
            return
        try:
            v = float(self.var.get())
        except ValueError:
            v = self.p.get("default") or 0
        v = round(v + d * self.step, self.dec)
        lo, hi = self.p.get("min"), self.p.get("max")
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        self.var.set(_fmt_num(v, self.dec))

    def _focus(self, on):
        self.focused = on
        self._paint()

    def _paint(self):
        color = C["err"] if self.err else C["accent"] if self.focused else C["border"]
        self.widget.configure(border_color=color)

    def raw(self):
        return self.var.get()

    def value(self):
        p, s = self.p, self.var.get().strip()
        try:
            v = int(s) if self.is_int else float(s)
        except ValueError:
            return None, "要填整數" if self.is_int else "要填數字"
        lo, hi = p.get("min"), p.get("max")
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            if lo is not None and hi is not None:
                return None, f"需介於 {_fmt_limit(lo)}～{_fmt_limit(hi)}"
            return None, f"不能小於 {_fmt_limit(lo)}" if lo is not None and v < lo else f"不能大於 {_fmt_limit(hi)}"
        return v, ""

    def set_enabled(self, on):
        self.enabled = on
        self.entry.configure(state="normal" if on else "disabled", text_color=C["text"] if on else C["faint"])
        for a in (self.up, self.down):
            a.configure(text_color=C["sub"] if on else C["faint"])

    def show_error(self, on):
        self.err = on
        self._paint()

    def focus(self):
        self.entry.focus_set()


class BoolField(Field):
    def __init__(self, master, p, value, on_change):
        self.var = tk.BooleanVar(value=bool(value))
        self.widget = ctk.CTkCheckBox(master, text=p["label"], variable=self.var, font=F.body,
                                      text_color=C["text"], text_color_disabled=C["faint"],
                                      fg_color=C["accent"], hover_color=C["accent_hover"],
                                      border_color=C["sub"], border_width=2, checkmark_color=C["white"],
                                      checkbox_width=18, checkbox_height=18, corner_radius=4,
                                      command=on_change)

    def raw(self):
        return self.var.get()

    def value(self):
        return bool(self.var.get()), ""

    def set_enabled(self, on):
        self.widget.configure(state="normal" if on else "disabled")


class ChoiceField(Field):
    def __init__(self, master, p, value, on_change):
        self.choices = list(p["choices"])
        names = [str(c) for c in self.choices]
        cur = str(value) if str(value) in names else str(p["default"])
        self.var = tk.StringVar(value=cur)
        self.widget = ctk.CTkOptionMenu(master, values=names, variable=self.var, height=32,
                                        corner_radius=RADIUS, font=F.body, dropdown_font=F.body,
                                        fg_color=C["input"], button_color=C["input"],
                                        button_hover_color=C["input_hover"], text_color=C["text"],
                                        text_color_disabled=C["faint"], dropdown_fg_color=C["panel"],
                                        dropdown_hover_color=C["accent"], dropdown_text_color=C["text"],
                                        dynamic_resizing=False, command=lambda _: on_change())

    def raw(self):
        return self.var.get()

    def value(self):
        s = self.var.get()
        return next((c for c in self.choices if str(c) == s), self.choices[0]), ""

    def set_enabled(self, on):
        self.widget.configure(state="normal" if on else "disabled")


class TextField(Field):
    def __init__(self, master, p, value, on_change):
        self.var = tk.StringVar(value="" if value is None else str(value))
        self.widget = ctk.CTkEntry(master, textvariable=self.var, height=32, corner_radius=RADIUS,
                                   font=F.body, fg_color=C["input"], border_color=C["border"],
                                   border_width=1, text_color=C["text"])
        self.var.trace_add("write", lambda *_: on_change())

    def raw(self):
        return self.var.get()

    def value(self):
        return self.var.get(), ""

    def set_enabled(self, on):
        self.widget.configure(state="normal" if on else "disabled",
                              text_color=C["text"] if on else C["faint"])

    def show_error(self, on):
        self.widget.configure(border_color=C["err"] if on else C["border"])


# ================================================================== 參數表單
class ParamForm:
    """依 params 動態產生欄位。label 欄固定寬、輸入欄填滿。"""
    LABEL_W = 150

    def __init__(self, master, params, values, on_change, make_special=None):
        """
        values        {key: 值或草稿}
        make_special  (master, p, value, on_change) → Field 或 None；用來產生出招流程編輯器等特殊欄位
        """
        self.frame = Box(master, "panel")
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(0, minsize=px(self.LABEL_W))
        self.on_change = on_change
        self.fields = {}       # key → (Field, p, 錯誤標籤)
        row = 0
        specials, normal = [], []
        for p in params:
            (specials if p.get("widget") and make_special else normal).append(p)

        for p in specials:                      # 特殊欄位（出招流程）放最上面，自帶標題
            v = values.get(p["key"], p["default"])
            fld = make_special(self.frame, p, v, self._changed)
            if fld is None:
                normal.insert(0, p)
                continue
            fld.widget.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, M))
            self.fields[p["key"]] = (fld, p, None)
            row += 1

        if specials and normal and len(self.fields):
            label(self.frame, "其他設定", F.section, "sub").grid(row=row, column=0, columnspan=2,
                                                                 sticky="w", pady=(S, S))
            row += 1

        for p in normal:
            v = values.get(p["key"], p["default"])
            if p["type"] is bool:
                box = Box(self.frame, "panel")
                box.grid(row=row, column=0, columnspan=2, sticky="w", pady=(XS, XS))
                fld = BoolField(box, p, v, self._changed)
                fld.widget.pack(side="left")
                if p.get("help"):
                    help_icon(box, p["help"]).pack(side="left", padx=(2, 0))
                self.fields[p["key"]] = (fld, p, None)
                row += 1
                continue
            lab = Box(self.frame, "panel")
            lab.grid(row=row, column=0, sticky="w", pady=(XS, XS))
            label(lab, p["label"], F.body).pack(side="left")
            if p.get("help"):
                help_icon(lab, p["help"]).pack(side="left", padx=(6, 0))
            if p.get("choices"):
                fld = ChoiceField(self.frame, p, v, self._changed)
            elif p["type"] in (int, float):
                fld = NumberField(self.frame, p, v, self._changed)
            else:
                fld = TextField(self.frame, p, v, self._changed)
            fld.widget.grid(row=row, column=1, sticky="ew", pady=(XS, XS), padx=(M, 0))
            err = label(self.frame, "", F.small, "err", anchor="w", height=16)
            err.grid(row=row + 1, column=1, sticky="w", padx=(M, 0), pady=(0, XS))
            err.grid_remove()
            self.fields[p["key"]] = (fld, p, err)
            row += 2
        self.refresh_errors()

    def _changed(self):
        self.refresh_errors()
        self.on_change()

    def refresh_errors(self):
        for key, (fld, p, err) in self.fields.items():
            _, msg = fld.value()
            fld.show_error(bool(msg))
            if err is not None:
                if msg:
                    err.configure(text=msg)
                    err.grid()
                else:
                    err.grid_remove()

    def errors(self):
        """[(Field, p, 訊息), ...]"""
        out = []
        for fld, p, _ in self.fields.values():
            _, msg = fld.value()
            if msg:
                out.append((fld, p, msg))
        return out

    def values(self):
        """目前沒有錯誤的欄位的值。"""
        out = {}
        for key, (fld, p, _) in self.fields.items():
            v, msg = fld.value()
            if not msg:
                out[key] = v
        return out

    def raws(self):
        return {key: fld.raw() for key, (fld, p, _) in self.fields.items()}

    def set_enabled(self, on):
        for fld, _, _ in self.fields.values():
            fld.set_enabled(on)


# ================================================================== 功能樹
class TaskTree:
    """
    ttk.Treeview：依任務路徑自動產生。資料夾的箭頭在右邊；資料夾不能被選取（點了只會展開／收合）。
    groups：一定要顯示的資料夾（自訂項目的類型），沒有項目時顯示一行提示。
    """
    HINT = "\x1f\x00"                 # 提示列 iid 的結尾

    def __init__(self, master, paths, on_select, scale=1.0, groups=None, on_context=None,
                 on_hint=None, on_key=None):
        self.on_select = on_select
        self.on_context = on_context      # (kind, path, x_root, y_root)，kind = "item"／"group"／"other"
        self.on_hint = on_hint            # 點了空類型的提示列 → (group_path)
        self.on_key = on_key              # ("rename"／"delete", path)
        self.current = None
        self.locked = False
        self.editable = set()             # 可以編輯的項目路徑
        self.groups = []

        self.style = ttk.Style(master)
        self.rescale(scale)

        self.widget = ttk.Treeview(master, style="Task.Treeview", show="tree", columns=("arrow",),
                                   selectmode="browse", takefocus=False)
        self._columns(scale)
        self.widget.tag_configure("folder", foreground=C["text"])
        self.widget.tag_configure("locked", foreground=C["faint"])
        self.widget.tag_configure("hint", foreground=C["sub"])
        self.widget.bind("<<TreeviewSelect>>", self._on_select)
        self.widget.bind("<<TreeviewOpen>>", lambda e: self.widget.after_idle(self._refresh_arrows))
        self.widget.bind("<<TreeviewClose>>", lambda e: self.widget.after_idle(self._refresh_arrows))
        self.widget.bind("<Button-1>", lambda e: self.widget.focus_set(), add="+")
        self.widget.bind("<Button-3>", self._on_right)
        self.widget.bind("<F2>", lambda e: self._key("rename"))
        self.widget.bind("<Delete>", lambda e: self._key("delete"))
        self.rebuild(paths, groups)

    def rescale(self, scale):
        """字型、行高跟著 Windows 顯示比例。"""
        st = self.style
        st.configure("Task.Treeview", background=C["panel"], fieldbackground=C["panel"],
                     foreground=C["text"], borderwidth=0, relief="flat",
                     font=F.tk(13, scale=scale), rowheight=round(32 * scale), indent=round(16 * scale))
        st.map("Task.Treeview", background=[("selected", C["sel"])],
               foreground=[("selected", C["accent_text"])])
        st.layout("Task.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.layout("Task.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.text", {"side": "left", "sticky": ""})]})])
        st.configure("Task.Treeview.Item", padding=(round(10 * scale), 0))
        if hasattr(self, "widget"):
            self._columns(scale)
            self.widget.tag_configure("hint", font=F.tk(11, scale=scale))

    def _columns(self, scale):
        self.widget.column("#0", stretch=True, width=round(160 * scale))
        self.widget.column("arrow", width=round(26 * scale), stretch=False, anchor="center")

    @staticmethod
    def iid(path):
        return "\x1f".join(path)

    @staticmethod
    def path_of(iid):
        return tuple(iid.split("\x1f"))

    # ---------------------------------------------------------------- 建立／重建
    def rebuild(self, paths, groups=None, editable=None):
        """paths：任務路徑（依顯示順序）；groups：一定要顯示的資料夾；editable：可以編輯的項目。"""
        w = self.widget
        closed = {i for i in self._all_iids() if not w.item(i, "open")}
        w.delete(*w.get_children(""))
        self.paths = [tuple(p) for p in paths]
        self.tasks = set(self.paths)
        self.groups = [tuple(g) for g in (groups or [])]
        self.editable = set(tuple(p) for p in (editable or []))

        def ensure(path):
            for i in range(len(path)):
                iid = self.iid(path[:i + 1])
                if not w.exists(iid):
                    parent = self.iid(path[:i]) if i else ""
                    w.insert(parent, "end", iid=iid, text=path[i], open=iid not in closed)

        # 依任務順序建立；類型資料夾放在它第一次出現的位置（沒有項目的類型跟在同一層後面）
        for path in self.paths:
            ensure(path)
        for g in self.groups:
            ensure(g)
            if not w.get_children(self.iid(g)):
                w.insert(self.iid(g), "end", iid=self.iid(g) + self.HINT, text="＋ 點這裡新增",
                         tags=("hint",))
        if self.current not in self.tasks:
            self.current = None
        self._refresh_arrows()
        self.set_locked(self.locked)
        if self.current:
            w.selection_set(self.iid(self.current))

    def _all_iids(self, item=""):
        out = []
        for c in self.widget.get_children(item):
            out.append(c)
            out += self._all_iids(c)
        return out

    def _refresh_arrows(self, item=""):
        for child in self.widget.get_children(item):
            if child.endswith(self.HINT):
                self.widget.set(child, "arrow", "")
                continue
            if self.widget.get_children(child):
                is_open = self.widget.item(child, "open")
                self.widget.set(child, "arrow", "▾" if is_open else "▸")
                self.widget.item(child, tags=("folder",))
                self._refresh_arrows(child)
            else:
                self.widget.set(child, "arrow", "")

    # ---------------------------------------------------------------- 事件
    def _on_select(self, _=None):
        sel = self.widget.selection()
        if not sel:
            return
        iid = sel[0]
        if iid.endswith(self.HINT):                         # 空類型的提示列
            self._restore()
            if not self.locked and self.on_hint:
                self.on_hint(self.path_of(iid[:-len(self.HINT)]))
            return
        path = self.path_of(iid)
        if path in self.tasks and not self.locked:
            if path != self.current:
                self.current = path
                self.on_select(path)
            return
        if path not in self.tasks and not self.locked:      # 資料夾：展開／收合
            self.widget.item(iid, open=not self.widget.item(iid, "open"))
            self._refresh_arrows()
        self._restore()

    def _on_right(self, e):
        if not self.on_context:
            return
        iid = self.widget.identify_row(e.y)
        if not iid:
            self.on_context("other", None, e.x_root, e.y_root)
            return
        if iid.endswith(self.HINT):
            iid = iid[:-len(self.HINT)]
        path = self.path_of(iid)
        if path in self.editable:
            if path != self.current and not self.locked:
                self.select(path, notify=True)
            kind = "item"
        elif path in self.groups:
            kind = "group"
        else:
            kind = "other"
        self.on_context(kind, path, e.x_root, e.y_root)

    def _key(self, name):
        if self.on_key and self.current in self.editable and not self.locked:
            self.on_key(name, self.current)
        return "break"

    def _restore(self):
        if self.current:
            self.widget.selection_set(self.iid(self.current))
        else:
            self.widget.selection_remove(self.widget.selection())

    # ---------------------------------------------------------------- 查詢
    def select(self, path, notify=False):
        """選取任務。notify=True 時也呼叫 on_select。"""
        path = tuple(path)
        if path not in self.tasks:
            return False
        changed = path != self.current
        self.current = path                        # 先設定，之後的 <<TreeviewSelect>> 就不會重複通知
        iid = self.iid(path)
        p = path[:-1]
        while p:                                   # 展開上層
            self.widget.item(self.iid(p), open=True)
            p = p[:-1]
        self._refresh_arrows()
        self.widget.see(iid)
        self.widget.selection_set(iid)
        if notify and changed:
            self.on_select(path)
        return True

    def first_task(self):
        def walk(item):
            for child in self.widget.get_children(item):
                path = self.path_of(child)
                if path in self.tasks:
                    return path
                found = walk(child)
                if found:
                    return found
        return walk("")

    def siblings(self, path):
        """同一個資料夾裡的任務（依顯示順序）。"""
        parent = self.iid(path[:-1]) if len(path) > 1 else ""
        return [self.path_of(c) for c in self.widget.get_children(parent) if self.path_of(c) in self.tasks]

    def bbox(self, path):
        try:
            return self.widget.bbox(self.iid(path), "#0") or None
        except tk.TclError:
            return None

    def set_locked(self, locked):
        """執行中：不能切換任務。"""
        self.locked = locked
        for path in self.tasks:
            if path != self.current:
                self.widget.item(self.iid(path), tags=("locked",) if locked else ())


# ================================================================== 日誌
class LogView:
    """tk.Text + ttk 捲軸（customtkinter 的捲軸重畫很慢，視窗調整大小會卡）。"""
    MAX_LINES = 3000

    def __init__(self, master, scale=1.0):
        self.widget = Box(master, "panel")
        self.widget.grid_rowconfigure(0, weight=1)
        self.widget.grid_columnconfigure(0, weight=1)
        self.text = tk.Text(self.widget, bg=C["panel"], fg=C["text"], bd=0, highlightthickness=0,
                            wrap="char", padx=0, pady=0, cursor="arrow", insertwidth=0,
                            selectbackground=C["accent"], selectforeground=C["white"], takefocus=False)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.sb = ttk.Scrollbar(self.widget, orient="vertical", command=self.text.yview,
                                style="Dark.Vertical.TScrollbar")
        self.sb.grid(row=0, column=1, sticky="ns", padx=(px(XS), 0))
        self._sb_val, self._sb_job = (0.0, 1.0), None
        self.text.configure(yscrollcommand=self._yscroll)
        self.text.tag_configure("warn", foreground=C["warn"])
        self.text.tag_configure("error", foreground=C["err"])
        self.rescale(scale)
        self.text.configure(state="disabled")

    def rescale(self, scale):
        try:
            indent = round((F.mono.measure("00:00:00") + F.body.measure("  ")) * scale)
        except Exception:
            indent = round(80 * scale)
        self.text.configure(font=F.tk(13, scale=scale), spacing1=round(2 * scale), spacing3=round(2 * scale))
        self.text.tag_configure("line", lmargin2=indent)
        self.text.tag_configure("t", foreground=C["sub"], font=F.tk(12, mono=True, scale=scale))
        self.sb.grid_configure(padx=(px(XS), 0))

    def _yscroll(self, first, last):
        self._sb_val = (first, last)
        if not self._sb_job:
            self._sb_job = self.text.after(40, self._flush_sb)

    def _flush_sb(self):
        self._sb_job = None
        first, last = (float(v) for v in self._sb_val)
        self.sb.set(first, last)
        if first <= 0.0 and last >= 1.0:          # 內容放得下就隱藏捲軸
            self.sb.grid_remove()
        else:
            self.sb.grid()

    def append(self, text, level="info"):
        self.append_many([(text, level)])

    def append_many(self, items):
        t = self.text
        at_bottom = t.yview()[1] >= 0.999
        t.configure(state="normal")
        for text, level in items:
            stamp = f"{datetime.datetime.now():%H:%M:%S}"
            tags = ("line",) + ((level,) if level in ("warn", "error") else ())
            t.insert("end", stamp, ("line", "t"))
            t.insert("end", "  " + str(text).rstrip("\n") + "\n", tags)
        lines = int(t.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            t.delete("1.0", f"{lines - self.MAX_LINES}.0")
        t.configure(state="disabled")
        if at_bottom:
            t.see("end")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class ScrollFrame:
    """
    可捲動的區域：tk.Canvas + Box + ttk 捲軸（取代 CTkScrollableFrame，調整大小時不會卡）。
    內容放在 self.inner；內容比區域短時自動隱藏捲軸；滑鼠在區域上時滾輪可以捲。
    """

    def __init__(self, master, bg="panel"):
        self.widget = Box(master, bg)
        self.widget.grid_rowconfigure(0, weight=1)
        self.widget.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.widget, bg=C[bg], bd=0, highlightthickness=0, yscrollincrement=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.sb = ttk.Scrollbar(self.widget, orient="vertical", command=self.canvas.yview,
                                style="Dark.Vertical.TScrollbar")
        self.inner = Box(self.canvas, bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._yscroll)
        self.inner.bind("<Configure>", lambda e: self._update(), add="+")
        self.canvas.bind("<Configure>", self._on_canvas, add="+")
        self.widget.bind("<Enter>", lambda e: self._wheel(True), add="+")
        self.widget.bind("<Leave>", self._leave, add="+")
        self._shown = False

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._update()

    def _update(self):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1
        if need != self._shown:
            self._shown = need
            if need:
                self.sb.grid(row=0, column=1, sticky="ns", padx=(2, 2), pady=2)
            else:
                self.sb.grid_remove()
                self.canvas.yview_moveto(0)

    def _yscroll(self, first, last):
        self.sb.set(first, last)

    def _leave(self, e):
        x, y = self.widget.winfo_pointerxy()
        w = self.widget.winfo_containing(x, y)
        while w is not None and w is not self.widget:      # 移到子元件上不算離開
            w = w.master
        if w is None:
            self._wheel(False)

    def _wheel(self, on):
        if on:
            self.widget.bind_all("<MouseWheel>", self._on_wheel)
            self.widget.bind_all("<Button-4>", lambda e: self._scroll(-1))
            self.widget.bind_all("<Button-5>", lambda e: self._scroll(1))
        else:
            self.widget.unbind_all("<MouseWheel>")
            self.widget.unbind_all("<Button-4>")
            self.widget.unbind_all("<Button-5>")

    def _on_wheel(self, e):
        self._scroll(-1 if e.delta > 0 else 1)

    def _scroll(self, d):
        if self._shown:
            self.canvas.yview_scroll(d * px(48), "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


def split_unit(label_text):
    """「每輪間隔(秒)」→ ("每輪間隔", "秒")"""
    m = re.match(r"^(.*?)\s*[（(]\s*(.+?)\s*[)）]\s*$", label_text)
    return (m.group(1), m.group(2)) if m else (label_text, "")
