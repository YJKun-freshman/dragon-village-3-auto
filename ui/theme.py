# -*- coding: utf-8 -*-
"""
配色、字型、間距。所有顏色都在這裡，元件裡不寫死色碼。

配色：A 深色科技藍（2026-11-06 使用者選定）
"""
import tkinter as tk
import tkinter.font as tkfont
import weakref
from tkinter import ttk

import customtkinter as ctk

# ------------------------------------------------------------------ 顏色
C = {
    "bg": "#1E1E1E",            # 視窗底色
    "panel": "#2B2B2B",         # 卡片
    "input": "#363636",         # 輸入框
    "input_hover": "#404040",
    "list_bg": "#232323",       # 步驟清單底色
    "border": "#444444",
    "border_hover": "#5A5A5A",
    "text": "#EDEDED",          # 主文字
    "sub": "#A0A0A0",           # 次要文字（對比 > 4.5:1）
    "faint": "#6E6E6E",         # 停用文字
    "accent": "#1F6AA5",        # 主色：科技藍
    "accent_hover": "#195685",
    "accent_text": "#5AA2DC",   # 深色底上的藍字
    "accent_dim": "#203445",    # 停用的主色按鈕
    "sel": "#293843",           # 選取列底色（主色 20%）
    "err": "#E5534B",
    "err_hover": "#3A2726",
    "warn": "#D29922",
    "ok": "#3FB950",
    "white": "#FFFFFF",
}

# ------------------------------------------------------------------ 間距（4 / 8 / 12 / 16 / 24）
XS, S, M, L, XL = 4, 8, 12, 16, 24
RADIUS = 6          # 按鈕、輸入框
CARD_RADIUS = 8     # 卡片

# ------------------------------------------------------------------ 字型
_SANS = ["Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans CJK TC", "PingFang TC",
         "Segoe UI", "Arial"]
_MONO = ["Consolas", "Cascadia Mono", "Noto Sans Mono CJK TC", "DejaVu Sans Mono", "Courier New"]


class _Fonts:
    """theme.init(root) 之後才能用。大小是 customtkinter 的單位（會跟著 Windows 縮放）。"""
    family = "TkDefaultFont"
    mono_family = "TkFixedFont"

    def init(self, root):
        have = set(tkfont.families(root))
        self.family = next((f for f in _SANS if f in have), "TkDefaultFont")
        self.mono_family = next((f for f in _MONO if f in have), "TkFixedFont")
        mk = lambda size, weight="normal", fam=None: ctk.CTkFont(family=fam or self.family, size=size, weight=weight)
        self.title = mk(18, "bold")      # 視窗標題
        self.h2 = mk(16, "bold")         # 任務名稱
        self.section = mk(12, "bold")    # 區塊標題（參數設定、日誌）
        self.body = mk(13)               # 內文、標籤、輸入
        self.body_bold = mk(13, "bold")
        self.small = mk(11)              # 提示、說明
        self.tiny = mk(10)
        self.arrow = mk(8)               # 數字欄的 ▲▼
        self.mono = mk(12, fam=self.mono_family)

    def tk(self, size, weight="normal", mono=False, scale=1.0):
        """給 ttk / tk.Menu 用的字型 tuple（負數 = 像素）。"""
        fam = self.mono_family if mono else self.family
        return (fam, -max(1, round(size * scale)), weight)


F = _Fonts()


def init(root):
    ctk.set_appearance_mode("dark")
    F.init(root)


# ------------------------------------------------------------------ 縮放（Windows 顯示比例）
_scale = [1.0]
_boxes = weakref.WeakSet()


def scale():
    return _scale[0]


def px(n):
    """未縮放的像素 → 實際像素（給 tk / ttk 元件用；customtkinter 元件會自己縮放）。"""
    return round(n * _scale[0])


def set_scale(value):
    """顯示比例改變時呼叫：重新套用所有 Box 的間距。"""
    _scale[0] = value
    for b in list(_boxes):
        try:
            b.rescale()
        except tk.TclError:
            pass


def _scaled(kw):
    out = dict(kw)
    for k in ("padx", "pady", "ipadx", "ipady"):
        if k in out:
            v = out[k]
            out[k] = tuple(px(x) for x in v) if isinstance(v, (tuple, list)) else px(v)
    return out


class Box(tk.Frame):
    """
    只用來排版的容器。用 tk.Frame（不用重畫）取代透明的 CTkFrame，視窗調整大小時比較不會卡。
    grid / pack 的間距會跟 customtkinter 一樣自動乘上顯示比例。
    """

    def __init__(self, master, bg, height=None, **kw):
        self._h = height
        super().__init__(master, bg=C.get(bg, bg), bd=0, highlightthickness=0, **kw)
        if height is not None:
            super().configure(height=px(height))
        self._geo = None
        _boxes.add(self)

    def grid(self, **kw):
        if kw:
            self._geo = ("grid", kw)
            super().grid(**_scaled(kw))
        else:
            super().grid()

    def pack(self, **kw):
        self._geo = ("pack", kw)
        super().pack(**_scaled(kw))

    def place(self, **kw):
        self._geo = ("place", kw)
        super().place(**kw)

    def rescale(self):
        if self._h is not None:
            super().configure(height=px(self._h))
        if not self._geo or not self.winfo_manager():
            return
        kind, kw = self._geo
        if kind == "grid":
            super().grid(**_scaled(kw))
        elif kind == "pack":
            super().pack_configure(**_scaled({k: v for k, v in kw.items() if k in ("padx", "pady", "ipadx", "ipady")}))


def style_ttk(root):
    """ttk 捲軸的深色樣式（比 customtkinter 的捲軸輕很多）。"""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.layout("Dark.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    st.configure("Dark.Vertical.TScrollbar", troughcolor=C["panel"], background=C["border"],
                 bordercolor=C["panel"], lightcolor=C["border"], darkcolor=C["border"],
                 relief="flat", borderwidth=0, arrowsize=px(8), gripcount=0)
    st.map("Dark.Vertical.TScrollbar", background=[("active", C["border_hover"]), ("pressed", C["border_hover"])],
           lightcolor=[("active", C["border_hover"])], darkcolor=[("active", C["border_hover"])])
    return st


# ------------------------------------------------------------------ 常用元件樣式
def primary_button(master, text, command=None, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(master, text=text, command=command, fg_color=C["accent"],
                         hover_color=C["accent_hover"], text_color=C["white"],
                         text_color_disabled="#7C8A96", corner_radius=RADIUS,
                         font=F.body_bold, **kw)


def outline_button(master, text, command=None, **kw):
    kw.setdefault("height", 32)
    kw.setdefault("font", F.small)
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent",
                         hover_color=C["input"], border_color=C["border"], border_width=1,
                         text_color=C["sub"], text_color_disabled=C["faint"],
                         corner_radius=RADIUS, **kw)


def chip_button(master, text, command=None, **kw):
    """出招流程的「加入」按鈕。"""
    kw.setdefault("height", 30)
    return ctk.CTkButton(master, text=text, command=command, fg_color=C["input"],
                         hover_color=C["input_hover"], border_color=C["border"], border_width=1,
                         text_color=C["text"], text_color_disabled=C["faint"],
                         corner_radius=RADIUS, font=F.small, **kw)


def card(master, **kw):
    return ctk.CTkFrame(master, fg_color=C["panel"], border_color=C["border"], border_width=1,
                        corner_radius=CARD_RADIUS, **kw)


def label(master, text="", font=None, color="text", **kw):
    return ctk.CTkLabel(master, text=text, font=font or F.body, text_color=C[color], **kw)


def set_primary_enabled(btn, enabled):
    """CTkButton 停用時底色不會變，這裡手動調暗。"""
    btn.configure(state="normal" if enabled else "disabled",
                  fg_color=C["accent"] if enabled else C["accent_dim"])


def set_stop_enabled(btn, enabled):
    """停止鈕：可以按時用紅色外框提示。"""
    btn.configure(state="normal" if enabled else "disabled",
                  border_color=C["err"] if enabled else C["border"],
                  text_color=C["err"] if enabled else C["sub"],
                  hover_color=C["err_hover"] if enabled else C["input"])


def menu_style(scale=1.0):
    """tk.Menu 的深色樣式。"""
    return dict(tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["accent"],
                activeforeground=C["white"], disabledforeground=C["faint"], bd=1,
                relief="solid", font=F.tk(13, scale=scale))
