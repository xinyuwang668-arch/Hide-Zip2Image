"""HideZipImage V3.1.0 新版界面（侧边栏 + 卡片式布局）。

界面全部使用 customtkinter，颜色统一写成 (浅色, 深色) 元组，
这样切换明暗主题时不需要重建控件。
"""

from __future__ import annotations

import os
import queue
import threading
import time
import traceback
from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk
from PIL import Image
from tkinter import filedialog
from tkinterdnd2 import DND_FILES, TkinterDnD

from . import core
from .core import (
    APP_NAME,
    APP_VERSION,
    ARCHIVE_EXTS,
    GITHUB_URL,
    IMAGE_EXTS,
    THEME_COLORS,
)
from .theme import ACCENTS, FONT_FAMILY, LIGHT, DARK


# --------------------------------------------------------------------------- #
# 颜色助手
# --------------------------------------------------------------------------- #
def c(key: str):
    """普通色 → (浅色, 深色)。"""
    return (LIGHT[key], DARK[key])


_ACTIVE_ACCENT = "蓝色"


def set_active_accent(name: str) -> None:
    """记录当前主题色，供默认参数使用。"""
    global _ACTIVE_ACCENT
    _ACTIVE_ACCENT = name if name in ACCENTS else "蓝色"


def ac(name: Optional[str] = None):
    """主色 → (浅色, 深色)，两套主题里主色相同。"""
    name = name or _ACTIVE_ACCENT
    return (ACCENTS.get(name, ACCENTS["蓝色"])[0],) * 2


def ac_hover(name: Optional[str] = None):
    name = name or _ACTIVE_ACCENT
    return (ACCENTS.get(name, ACCENTS["蓝色"])[1],) * 2


def font(size: int = 13, weight: str = "normal"):
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def shorten(text: str, limit: int = 46) -> str:
    if len(text) <= limit:
        return text
    head = max(8, limit // 2 - 2)
    tail = limit - head - 1
    return f"{text[:head]}…{text[-tail:]}"


def ellipsis_middle(path: str, limit: int = 52) -> str:
    return shorten(path, limit)


# --------------------------------------------------------------------------- #
# 通用小部件
# --------------------------------------------------------------------------- #
class Card(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("corner_radius", 16)
        kwargs.setdefault("fg_color", c("card"))
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", c("border"))
        super().__init__(master, **kwargs)


class MutedLabel(ctk.CTkLabel):
    def __init__(self, master, text: str = "", size: int = 12, **kwargs):
        kwargs.setdefault("text_color", c("muted"))
        kwargs.setdefault("font", font(size))
        kwargs.setdefault("anchor", "w")
        super().__init__(master, text=text, **kwargs)


class AccentButton(ctk.CTkButton):
    def __init__(self, master, app=None, accent: Optional[str] = None, **kwargs):
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("height", 42)
        kwargs.setdefault("font", font(14, "bold"))
        kwargs.setdefault("fg_color", ac(accent))
        kwargs.setdefault("hover_color", ac_hover(accent))
        kwargs.setdefault("text_color", "#FFFFFF")
        super().__init__(master, **kwargs)


class GhostButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("height", 36)
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", c("card_hover"))
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", c("border"))
        kwargs.setdefault("text_color", c("text"))
        kwargs.setdefault("font", font(13))
        super().__init__(master, **kwargs)


class PageTitle(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=font(20, "bold"), text_color=c("text"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        if subtitle:
            MutedLabel(self, subtitle).grid(row=1, column=0, sticky="w", pady=(2, 0))


class Dialog(ctk.CTkToplevel):
    """统一的模态对话框：标题 + 正文 + 若干按钮。"""

    def __init__(
        self,
        app,
        *,
        title: str,
        message: str = "",
        detail: str = "",
        kind: str = "info",
        buttons: Optional[list[tuple[str, Optional[Callable[[], None]]]]] = None,
        width: int = 460,
    ):
        super().__init__(app)
        self.app = app
        self._callbacks: list[Optional[Callable[[], None]]] = []
        self.title(title)
        self.configure(fg_color=c("bg"))
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        accent = "蓝色"
        icon_color = c("text")
        if kind == "error":
            icon_color = c("danger")
        elif kind == "success":
            icon_color = c("success")
        elif kind == "warning":
            icon_color = c("warning")

        body = ctk.CTkFrame(self, fg_color=c("card"), corner_radius=14, border_width=1, border_color=c("border"))
        body.pack(fill="both", expand=True, padx=16, pady=16)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text={"info": "ⓘ", "error": "✕", "success": "✓", "warning": "!"}.get(kind, "ⓘ"),
            font=font(20, "bold"), text_color=icon_color, width=28,
        ).grid(row=0, column=0, sticky="w", padx=(18, 0), pady=(16, 0))
        ctk.CTkLabel(
            body, text=title, font=font(16, "bold"), text_color=c("text"), anchor="w",
            wraplength=width - 90, justify="left",
        ).grid(row=0, column=1, sticky="w", padx=(4, 18), pady=(16, 0))
        body.grid_columnconfigure(1, weight=1)

        row = 1
        if message:
            ctk.CTkLabel(
                body, text=message, font=font(13), text_color=c("muted"), anchor="w",
                justify="left", wraplength=width - 70,
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=18, pady=(10, 0))
            row += 1
        if detail:
            detail_box = ctk.CTkTextbox(
                body, height=120, corner_radius=8, fg_color=c("card_alt"),
                border_width=0, text_color=c("text"), font=font(12), wrap="word",
            )
            detail_box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=18, pady=(10, 0))
            detail_box.insert("1.0", detail)
            detail_box.configure(state="disabled")
            row += 1

        button_row = ctk.CTkFrame(body, fg_color="transparent")
        button_row.grid(row=row, column=0, columnspan=2, sticky="e", padx=18, pady=(16, 16))
        buttons = buttons or [("知道了", None)]
        for index, (label, callback) in enumerate(buttons):
            if index == 0:
                button = AccentButton(
                    button_row, text=label, height=36, width=96,
                    command=lambda cb=callback: self._run(cb),
                )
            else:
                button = GhostButton(
                    button_row, text=label, height=36, width=96,
                    command=lambda cb=callback: self._run(cb),
                )
            button.pack(side="right", padx=(8, 0))
            self._callbacks.append(callback)

        self.update_idletasks()
        self._center(width)
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _center(self, width: int) -> None:
        try:
            app_x = self.app.winfo_rootx()
            app_y = self.app.winfo_rooty()
            app_w = self.app.winfo_width()
            app_h = self.app.winfo_height()
            height = self.winfo_reqheight()
            self.geometry(f"{width}x{height}+{app_x + (app_w - width) // 2}+{app_y + (app_h - height) // 3}")
        except tk.TclError:
            pass

    def _run(self, callback: Optional[Callable[[], None]]) -> None:
        self._close()
        if callback is not None:
            callback()

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class Toast(ctk.CTkFrame):
    """右下角浮层提示，几秒后自动消失。"""

    ICONS = {"info": "ⓘ", "success": "✓", "error": "✕", "warning": "!"}

    def __init__(self, app):
        super().__init__(app, corner_radius=12, border_width=1, fg_color=c("card"), border_color=c("border"))
        self.app = app
        self._after_id = None
        self.icon = ctk.CTkLabel(self, text="ⓘ", font=font(15, "bold"), width=24, text_color=c("text"))
        self.icon.pack(side="left", padx=(14, 6), pady=12)
        self.label = ctk.CTkLabel(self, text="", font=font(13), text_color=c("text"), anchor="w", justify="left")
        self.label.pack(side="left", padx=(0, 16), pady=12)

    def show(self, text: str, kind: str = "info", duration: int = 3200) -> None:
        colors = {
            "info": c("text"),
            "success": c("success"),
            "error": c("danger"),
            "warning": c("warning"),
        }
        self.icon.configure(text=self.ICONS.get(kind, "ⓘ"), text_color=colors.get(kind, c("text")))
        self.label.configure(text=text, wraplength=360)
        self.place(relx=0.985, rely=0.97, anchor="se")
        self.lift()
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = self.after(duration, self.hide)

    def hide(self) -> None:
        self._after_id = None
        try:
            self.place_forget()
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- #
# 鎷栨嫿鍗＄墖
# --------------------------------------------------------------------------- #
class DropCard(Card):
    """可点击、可拖拽的文件槽位。"""

    def __init__(
        self,
        master,
        app,
        *,
        kind: str,
        title: str,
        hint: str,
        on_pick: Optional[Callable[[], None]] = None,
        on_change: Optional[Callable[[], None]] = None,
        height: int = 190,
    ):
        super().__init__(master, height=height)
        self.app = app
        self.kind = kind  # "image" | "archive"
        self.on_pick = on_pick
        self.on_change = on_change
        self.path = ""
        self._thumb = None
        self._normal_border = c("border")
        self.configure(border_color=self._normal_border)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        body.grid_columnconfigure(1, weight=1)

        self.preview = ctk.CTkFrame(body, width=64, height=64, corner_radius=14, fg_color=c("card_alt"))
        self.preview.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        self.preview.grid_propagate(False)
        self.preview_label = ctk.CTkLabel(
            self.preview, text="+", font=font(24, "bold"), text_color=c("faint")
        )
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        self.head = ctk.CTkLabel(body, text=title, font=font(15, "bold"), text_color=c("text"), anchor="w")
        self.head.grid(row=0, column=1, sticky="w")
        self.name = ctk.CTkLabel(
            body, text="点击选择，或直接拖入文件", font=font(13), text_color=c("muted"),
            anchor="w", justify="left",
        )
        self.name.grid(row=1, column=1, sticky="w", pady=(2, 0))

        self.meta = MutedLabel(body, hint, size=11)
        self.meta.grid(row=2, column=1, sticky="w", pady=(6, 0))

        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.clear_btn = ctk.CTkButton(
            self.actions, text="清除", width=64, height=28, corner_radius=8,
            fg_color="transparent", hover_color=c("card_hover"), text_color=c("muted"),
            font=font(12), command=self.clear,
        )
        self.clear_btn.pack(side="right")

        self._bind_click(self)
        self._register_dnd(self)

    # -- 浜や簰 --------------------------------------------------------------- #
    def _bind_click(self, widget) -> None:
        try:
            widget.bind("<Button-1>", self._on_click, add="+")
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkButton):
                continue
            self._bind_click(child)

    def _register_dnd(self, widget) -> None:
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", self._on_drag_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drag_leave)
        except (tk.TclError, AttributeError):
            pass
        for child in widget.winfo_children():
            self._register_dnd(child)

    def _on_click(self, _event=None) -> None:
        if self.app.busy:
            return
        if self.on_pick is not None:
            self.on_pick()

    def _on_drag_enter(self, _event=None) -> None:
        self.configure(border_color=ac(self.app.accent), border_width=2)

    def _on_drag_leave(self, _event=None) -> None:
        self.configure(border_color=self._normal_border, border_width=1)

    def _on_drop(self, event) -> None:
        self._on_drag_leave()
        paths = core.clean_drop_path(getattr(event, "data", ""))
        self.app.handle_dropped(paths, preferred=self.kind)

    # -- 数据 ----------------------------------------------------------- #
    def set_path(self, path: str) -> None:
        self.path = path or ""
        self._render()

    def clear(self) -> None:
        self.path = ""
        self._render()
        if self.on_change is not None:
            self.on_change()

    def _render(self) -> None:
        if not self.path:
            self.preview_label.configure(image=None, text="+", text_color=c("faint"))
            self.name.configure(text="点击选择，或直接拖入文件", text_color=c("muted"))
            self.meta.configure(text=self._default_hint())
            self.clear_btn.pack_forget()
            return

        self.clear_btn.pack(side="right")
        name = os.path.basename(self.path)
        self.name.configure(text=shorten(name, 34), text_color=c("text"))
        if self.kind == "image":
            self._render_image()
        else:
            try:
                size = os.path.getsize(self.path)
            except OSError:
                size = 0
            ext = os.path.splitext(self.path)[1].lower().lstrip(".").upper() or "未知"
            self.preview_label.configure(image=None, text=ext[:4], text_color=ac(self.app.accent))
            self.meta.configure(text=f"{core.human_size(size)} · {ext} 压缩包")

    def _default_hint(self) -> str:
        return "支持 JPG / PNG / WEBP / BMP" if self.kind == "image" else "支持 ZIP / RAR / 7Z"

    def _render_image(self) -> None:
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        width = height = 0
        try:
            with Image.open(self.path) as img:
                width, height = img.size
                preview = img.convert("RGB")
                preview.thumbnail((56, 56))
                self._thumb = ctk.CTkImage(
                    light_image=preview, dark_image=preview, size=preview.size
                )
            self.preview_label.configure(image=self._thumb, text="")
        except Exception:
            self.preview_label.configure(image=None, text="IMG", text_color=ac(self.app.accent))
        resolution = f"{width}×{height}" if width and height else "无法读取尺寸"
        self.meta.configure(text=f"{resolution} · {core.human_size(size)}")


# --------------------------------------------------------------------------- #
# 输出路径行
# --------------------------------------------------------------------------- #
class PathRow(ctk.CTkFrame):
    def __init__(self, master, label: str, command: Callable[[], None], **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.label = ctk.CTkLabel(
            self, text=label, font=font(12), text_color=c("muted"), width=64, anchor="w"
        )
        self.label.grid(row=0, column=0, sticky="w")
        self.entry = ctk.CTkEntry(
            self, height=36, corner_radius=9, fg_color=c("card_alt"), border_width=1,
            border_color=c("border"), text_color=c("text"), font=font(12),
            placeholder_text="选择保存位置…",
        )
        self.entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        self.button = GhostButton(self, text="浏览", width=64, height=36, command=command)
        self.button.grid(row=0, column=2)

    def set(self, value: str) -> None:
        self.entry.delete(0, "end")
        if value:
            self.entry.insert(0, value)

    def get(self) -> str:
        return self.entry.get().strip()


# --------------------------------------------------------------------------- #
# 进度面板
# --------------------------------------------------------------------------- #
class ProgressPanel(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._start = 0.0
        self._total = 0
        self._value = 0.0

        self.bar = ctk.CTkProgressBar(
            self, height=8, corner_radius=4, fg_color=c("card_alt"),
            progress_color=ac(app.accent),
        )
        self.bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.bar.set(0)

        self.status = MutedLabel(self, "就绪", size=11)
        self.status.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.stat = ctk.CTkLabel(
            self, text="", font=font(11), text_color=c("faint"), anchor="e"
        )
        self.stat.grid(row=1, column=1, sticky="e", pady=(8, 0))
        self.cancel_btn = ctk.CTkButton(
            self, text="取消", width=64, height=26, corner_radius=7,
            fg_color="transparent", hover_color=c("card_hover"), border_width=1,
            border_color=c("border"), text_color=c("muted"), font=font(11),
            command=self._cancel,
        )
        self.cancel_btn.grid(row=1, column=2, sticky="e", padx=(10, 0), pady=(8, 0))
        self.cancel_btn.grid_remove()

    def _cancel(self) -> None:
        self.status.configure(text="正在取消…")
        self.cancel_btn.configure(state="disabled")
        self.app.cancel_current()

    def reset(self, text: str = "就绪") -> None:
        self._start = 0.0
        self._total = 0
        self._value = 0.0
        self.bar.set(0)
        self.status.configure(text=text)
        self.stat.configure(text="")
        self.cancel_btn.grid_remove()

    def begin(self, total_bytes: int = 0) -> None:
        self._start = time.monotonic()
        self._total = max(0, total_bytes)
        self._value = 0.0
        self.bar.set(0)
        self.cancel_btn.configure(state="normal")
        self.cancel_btn.grid()
        self.status.configure(text="正在处理…")

    def set_progress(self, value: float, text: str) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._value = value
        self.bar.set(value)
        if text:
            self.status.configure(text=text)
        elapsed = time.monotonic() - self._start
        if self._total > 0 and elapsed > 0.4:
            done = value * self._total
            speed = done / elapsed
            remain = (self._total - done) / speed if speed > 0 else 0
            self.stat.configure(
                text=f"{core.human_size(speed)}/s · 剩余 {core.human_duration(remain)}"
            )

    def finish(self, text: str = "完成") -> None:
        self.bar.set(1.0)
        self.status.configure(text=text)
        elapsed = time.monotonic() - self._start
        if self._total > 0 and elapsed > 0:
            self.stat.configure(text=f"耗时 {core.human_duration(elapsed)}")
        self.cancel_btn.grid_remove()


# --------------------------------------------------------------------------- #
# 开关行
# --------------------------------------------------------------------------- #
class SwitchRow(ctk.CTkFrame):
    def __init__(self, master, title: str, description: str, variable, command=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=font(13), text_color=c("text"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        if description:
            MutedLabel(self, description, size=11).grid(row=1, column=0, sticky="w")
        self.switch = ctk.CTkSwitch(
            self, text="", width=44, switch_width=40, switch_height=20,
            progress_color=ac("蓝色"), button_color="#FFFFFF", fg_color=c("border"),
            variable=variable, command=command,
        )
        self.switch.grid(row=0, column=1, rowspan=2, sticky="e")


# --------------------------------------------------------------------------- #
# 隐藏页
# --------------------------------------------------------------------------- #
class HidePage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(
            master, fg_color="transparent",
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.app = app
        self.output_custom = False
        self._build()
        self.apply_settings()

    # -- 构建 ----------------------------------------------------------- #
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        PageTitle(
            self, "隐藏文件", "把压缩包追加到图片尾部 —— 图片照常能打开，压缩包悄悄藏在里面",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew")
        cards.grid_columnconfigure((0, 1), weight=1, uniform="drop")
        self.image_card = DropCard(
            cards, self.app, kind="image", title="封面图片",
            hint="支持 JPG / PNG / WEBP / BMP", on_pick=self.choose_image,
            on_change=self._on_cover_changed,
        )
        self.image_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.archive_card = DropCard(
            cards, self.app, kind="archive", title="要隐藏的压缩包",
            hint="支持 ZIP / RAR / 7Z", on_pick=self.choose_archive,
            on_change=self._on_archive_changed,
        )
        self.archive_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # 输出
        out = Card(self)
        out.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        out.grid_columnconfigure(0, weight=1)
        out_inner = ctk.CTkFrame(out, fg_color="transparent")
        out_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        out_inner.grid_columnconfigure(0, weight=1)
        self.output_row = PathRow(out_inner, "保存到", self.choose_output)
        self.output_row.grid(row=0, column=0, sticky="ew")
        self.output_row.entry.bind("<KeyRelease>", self._on_output_typed)
        reset_btn = ctk.CTkButton(
            out_inner, text="恢复默认", height=26, width=72, corner_radius=7,
            fg_color="transparent", hover_color=c("card_hover"), text_color=c("muted"),
            font=font(11), command=self.reset_output,
        )
        reset_btn.grid(row=1, column=0, sticky="e", pady=(6, 0))

        # 选项
        opt = Card(self)
        opt.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        opt.grid_columnconfigure(0, weight=1)
        opt_inner = ctk.CTkFrame(opt, fg_color="transparent")
        opt_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        opt_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            opt_inner, text="选项", font=font(13, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        separator = ctk.CTkFrame(opt_inner, height=1, fg_color=c("border_soft"))
        separator.grid(row=1, column=0, sticky="ew", pady=(8, 10))

        self.encrypt_var = tk.BooleanVar(value=False)
        self.encrypt_row = SwitchRow(
            opt_inner, "AES-256 密码加密",
            "把压缩包重新封装成加密 ZIP，解压时需要输入密码", self.encrypt_var,
            command=self._toggle_encrypt,
        )
        self.encrypt_row.grid(row=2, column=0, sticky="ew")

        self.pass_frame = ctk.CTkFrame(opt_inner, fg_color="transparent")
        self.pass_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.pass_frame.grid_columnconfigure(0, weight=1)
        self.password_entry = ctk.CTkEntry(
            self.pass_frame, height=38, corner_radius=9, fg_color=c("card_alt"),
            border_width=1, border_color=c("border"), text_color=c("text"),
            font=font(13), placeholder_text="设置密码（至少 4 位）", show="●",
        )
        self.password_entry.grid(row=0, column=0, sticky="ew")
        self.password_confirm = ctk.CTkEntry(
            self.pass_frame, height=38, corner_radius=9, fg_color=c("card_alt"),
            border_width=1, border_color=c("border"), text_color=c("text"),
            font=font(13), placeholder_text="再输入一次确认", show="●",
        )
        self.password_confirm.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.show_pass_var = tk.BooleanVar(value=False)
        show_pass = ctk.CTkCheckBox(
            self.pass_frame, text="显示密码", variable=self.show_pass_var,
            font=font(11), text_color=c("muted"), fg_color=ac("蓝色"),
            hover_color=ac_hover("蓝色"), width=90, checkbox_width=16, checkbox_height=16,
            command=self._toggle_password_visible,
        )
        show_pass.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.pass_frame.grid_remove()

        self.verify_var = tk.BooleanVar(value=True)
        self.verify_row = SwitchRow(
            opt_inner, "完成后校验",
            "重新检测输出文件并比对 SHA-256，确认隐藏结果完整无误", self.verify_var,
            command=self._save_options,
        )
        self.verify_row.grid(row=4, column=0, sticky="ew", pady=(14, 0))

        # 鎿嶄綔
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        action.grid_columnconfigure(1, weight=1)
        self.start_btn = AccentButton(
            action, text="开始隐藏", width=168, height=46, command=self.start,
        )
        self.start_btn.grid(row=0, column=0, sticky="w")
        self.progress = ProgressPanel(action, self.app)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(18, 0))

        # 缁撴灉
        self.result = Card(self)
        self.result.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.result.grid_columnconfigure(0, weight=1)
        self.result_label = ctk.CTkLabel(
            self.result, text="", font=font(13), text_color=c("text"), anchor="w", justify="left",
        )
        self.result_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        result_buttons = ctk.CTkFrame(self.result, fg_color="transparent")
        result_buttons.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        GhostButton(result_buttons, text="打开所在文件夹", width=130, height=32, command=self._open_output).pack(side="left")
        GhostButton(result_buttons, text="复制路径", width=90, height=32, command=self._copy_output).pack(side="left", padx=(8, 0))
        self.result.grid_remove()

    # -- 设置同步 ----------------------------------------------------------- #
    def apply_settings(self) -> None:
        settings = self.app.settings
        self.encrypt_var.set(bool(settings.get("encrypt_by_default", False)))
        self.verify_var.set(bool(settings.get("verify_after_hide", True)))
        self._toggle_encrypt(animate=False)

    def _save_options(self) -> None:
        self.app.settings.update({
            "encrypt_by_default": bool(self.encrypt_var.get()),
            "verify_after_hide": bool(self.verify_var.get()),
        })
        self.app.settings.save()

    def _toggle_encrypt(self, animate: bool = True) -> None:
        if self.encrypt_var.get():
            self.pass_frame.grid()
        else:
            self.pass_frame.grid_remove()
            self.password_entry.delete(0, "end")
            self.password_confirm.delete(0, "end")
        self._save_options()

    def _toggle_password_visible(self) -> None:
        show = "" if self.show_pass_var.get() else "●"
        self.password_entry.configure(show=show)
        self.password_confirm.configure(show=show)

    # -- 文件选择 ------------------------------------------------------- #
    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择封面图片",
            initialdir=self.app.settings.get("last_image_dir") or self.app.settings.get("default_output_dir") or "",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            self.set_image(path)

    def choose_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="选择要隐藏的压缩包",
            initialdir=self.app.settings.get("last_archive_dir") or "",
            filetypes=[("压缩包", "*.zip *.rar *.7z"), ("所有文件", "*.*")],
        )
        if path:
            self.set_archive(path)

    def choose_output(self) -> None:
        image = self.image_card.path
        initial = self.output_row.get() or (image and self._default_output(image)) or ""
        extension = os.path.splitext(image)[1] if image else ".png"
        path = filedialog.asksaveasfilename(
            title="选择保存位置",
            initialdir=os.path.dirname(initial) if initial else "",
            initialfile=os.path.basename(initial) if initial else "",
            defaultextension=extension,
            filetypes=[("图片文件", f"*{extension}"), ("所有文件", "*.*")],
        )
        if path:
            self.output_custom = True
            self.output_row.set(path)

    def _on_output_typed(self, _event=None) -> None:
        current = self.output_row.get()
        if current and self.image_card.path:
            self.output_custom = current != self._default_output(self.image_card.path)

    # -- 路径设置 ----------------------------------------------------------- #
    def set_image(self, path: str) -> None:
        self.image_card.set_path(path)
        self.app.settings.set("last_image_dir", os.path.dirname(path))
        self._on_cover_changed()

    def set_archive(self, path: str) -> None:
        self.archive_card.set_path(path)
        self.app.settings.set("last_archive_dir", os.path.dirname(path))
        self._on_archive_changed()

    def _on_cover_changed(self) -> None:
        image = self.image_card.path
        if image and not self.output_custom:
            self.output_row.set(self._default_output(image))
        elif not image and not self.output_custom:
            self.output_row.set("")

    def _on_archive_changed(self) -> None:
        """压缩包变更后刷新结果区（隐藏结果与所选文件无关，只需清掉旧提示）。"""
        if not self.app.busy:
            self.progress.reset("就绪")

    def reset_output(self) -> None:
        self.output_custom = False
        if self.image_card.path:
            self.output_row.set(self._default_output(self.image_card.path))
        else:
            self.output_row.set("")

    def _default_output(self, image: str) -> str:
        stem, ext = os.path.splitext(os.path.basename(image))
        mode = self.app.settings.get("output_mode", "same_folder")
        folder = self.app.settings.get("default_output_dir") or ""
        if mode == "custom" and folder:
            base = folder
        else:
            base = os.path.dirname(image)
        return os.path.join(base, f"{stem}_hidden{ext}")

    # -- 执行 --------------------------------------------------------------- #
    def start(self) -> None:
        if self.app.busy:
            return
        image = self.image_card.path
        archive = self.archive_card.path
        if not image or not os.path.isfile(image):
            Dialog(self.app, title="还没选封面图片", message="请先选择一张图片作为封面。", kind="warning")
            return
        if not archive or not os.path.isfile(archive):
            Dialog(self.app, title="还没选压缩包", message="请选择要隐藏的 ZIP / RAR / 7Z 文件。", kind="warning")
            return

        output = self.output_row.get()
        if not output:
            output = self._default_output(image)
            self.output_row.set(output)

        image_ext = os.path.splitext(image)[1].lower()
        output_ext = os.path.splitext(output)[1].lower()
        if output_ext != image_ext:
            output = os.path.splitext(output)[0] + image_ext
            self.output_row.set(output)
            self.app.toast(f"输出扩展名已改为 {image_ext}，否则图片可能无法打开", "warning")

        folder = os.path.dirname(os.path.abspath(output)) or "."
        if not os.path.isdir(folder):
            Dialog(self.app, title="保存文件夹不存在", message=f"找不到文件夹：\n{folder}", kind="error")
            return
        if core.same_path(output, image) or core.same_path(output, archive):
            Dialog(
                self.app, title="保存位置冲突",
                message="输出文件不能和输入文件相同，否则会覆盖原文件。", kind="error",
            )
            return

        encrypt = bool(self.encrypt_var.get())
        password = ""
        if encrypt:
            password = self.password_entry.get()
            confirm = self.password_confirm.get()
            if len(password) < 4:
                Dialog(self.app, title="密码太短", message="密码至少需要 4 位。", kind="warning")
                return
            if password != confirm:
                Dialog(self.app, title="两次密码不一致", message="请重新确认密码。", kind="warning")
                return

        if os.path.exists(output) and not self.app.settings.get("auto_overwrite", False):
            def do_confirm() -> None:
                self._launch(image, archive, output, encrypt, password)

            Dialog(
                self.app, title="文件已存在",
                message=f"输出位置已经有同名文件：\n{os.path.basename(output)}\n要覆盖它吗？",
                kind="warning",
                buttons=[("覆盖", do_confirm), ("取消", None)],
            )
            return

        self._launch(image, archive, output, encrypt, password)

    def _launch(self, image: str, archive: str, output: str, encrypt: bool, password: str) -> None:
        total = 0
        try:
            total = os.path.getsize(image) + os.path.getsize(archive)
        except OSError:
            pass

        verify = bool(self.verify_var.get())
        self.result.grid_remove()
        self.app.set_busy(True, "正在隐藏…")
        self.progress.reset("准备中…")
        self.progress.begin(total)
        self.app.logbook.log(
            f"开始隐藏：{os.path.basename(archive)} → {os.path.basename(output)}"
            + ("（AES-256）" if encrypt else "")
        )

        def work():
            return core.hide_archive(
                image, archive, output,
                encrypt=encrypt, password=password,
                overwrite=True, verify=verify,
                progress=lambda fraction, text: self.app.post_progress(self.progress, fraction, text),
                cancel_event=self.app.cancel_event,
            )

        def done(result) -> None:
            self.app.set_busy(False)
            self.progress.finish("隐藏完成")
            try:
                self.app.settings.set("last_output_dir", os.path.dirname(result.output))
                self.app.settings.save()
            except Exception:
                pass
            self._show_result(result)
            self.app.logbook.log(
                f"隐藏成功：{result.output}（{core.human_size(result.total_bytes)}"
                f"，{core.human_duration(result.elapsed)}）"
            )
            self.app.toast("隐藏完成，图片照常可以打开", "success")

        def fail(exc: BaseException) -> None:
            self.app.set_busy(False)
            if isinstance(exc, core.OperationCancelled):
                self.progress.reset("已取消")
                self.app.toast("已取消", "info")
                self.app.logbook.log("隐藏已取消")
                return
            self.progress.reset("失败")
            self.app.logbook.log("隐藏失败", exc)
            Dialog(
                self.app, title="隐藏失败", message=str(exc) or exc.__class__.__name__,
                detail=traceback.format_exc(limit=3), kind="error",
            )

        self.app.run_bg(work, done, fail, label="hide")

    def _show_result(self, result) -> None:
        self._last_output = result.output
        lines = [
            f"已写入 {core.human_size(result.total_bytes)}",
            f"耗时 {core.human_duration(result.elapsed)}",
            f"压缩包偏移 {result.detection.offset}",
        ]
        if result.encrypted:
            lines.append("已使用 AES-256 加密")
        if result.verified:
            lines.append("SHA-256 校验通过")
        self.result_label.configure(text=" · ".join(lines))
        self.result.grid()

    def _open_output(self) -> None:
        path = getattr(self, "_last_output", "")
        if path:
            core.open_folder(os.path.dirname(path))

    def _copy_output(self) -> None:
        path = getattr(self, "_last_output", "")
        if not path:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
            self.app.toast("路径已复制", "success")
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- #
# 提取页
# --------------------------------------------------------------------------- #
class ExtractPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(
            master, fg_color="transparent",
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.app = app
        self.detection = core.Detection()
        self.output_custom = False
        self._detect_token = 0
        self._last_output = ""
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        PageTitle(
            self, "提取文件", "从图片尾部把藏进去的压缩包完整取出来",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.drop = DropCard(
            self, self.app, kind="image", title="被隐藏过的图片", hint="拖进来后会自动检测",
            on_pick=self.choose_file, on_change=self._on_file_changed, height=170,
        )
        self.drop.grid(row=1, column=0, sticky="ew")

        info = Card(self)
        info.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        info.grid_columnconfigure((0, 1), weight=1, uniform="info")
        self.info_labels: dict[str, ctk.CTkLabel] = {}
        items = [("类型", "kind"), ("压缩包大小", "size"), ("起始偏移", "offset"), ("结构校验", "valid")]
        for index, (title, key) in enumerate(items):
            cell = ctk.CTkFrame(info, fg_color="transparent")
            cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=16, pady=(12 if index < 2 else 8, 12 if index >= 2 else 0))
            MutedLabel(cell, title, size=11).pack(anchor="w")
            value = ctk.CTkLabel(cell, text="—", font=font(14, "bold"), text_color=c("text"), anchor="w")
            value.pack(anchor="w", pady=(2, 0))
            self.info_labels[key] = value

        out = Card(self)
        out.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        out.grid_columnconfigure(0, weight=1)
        out_inner = ctk.CTkFrame(out, fg_color="transparent")
        out_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        out_inner.grid_columnconfigure(0, weight=1)
        self.output_row = PathRow(out_inner, "保存为", self.choose_output)
        self.output_row.grid(row=0, column=0, sticky="ew")

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        action.grid_columnconfigure(1, weight=1)
        self.start_btn = AccentButton(action, text="提取压缩包", width=168, height=46, command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="w")
        self.progress = ProgressPanel(action, self.app)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(18, 0))

        self.result = Card(self)
        self.result.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.result.grid_columnconfigure(0, weight=1)
        self.result_label = ctk.CTkLabel(
            self.result, text="", font=font(13), text_color=c("text"), anchor="w",
        )
        self.result_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        buttons = ctk.CTkFrame(self.result, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        GhostButton(buttons, text="打开所在文件夹", width=130, height=32, command=self._open_output).pack(side="left")
        GhostButton(buttons, text="复制路径", width=90, height=32, command=self._copy_output).pack(side="left", padx=(8, 0))
        self.result.grid_remove()

        self.progress.reset("等待选择图片")

    # -- 选择与检测 --------------------------------------------------------- #
    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择被隐藏过的图片",
            initialdir=self.app.settings.get("last_extract_dir") or "",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            self.set_path(path)

    def set_path(self, path: str) -> None:
        self.drop.set_path(path)
        self.app.settings.set("last_extract_dir", os.path.dirname(path))
        self._on_file_changed()

    def _on_file_changed(self) -> None:
        path = self.drop.path
        self.result.grid_remove()
        if not path:
            self.detection = core.Detection()
            self._render_info()
            self.progress.reset("等待选择图片")
            return

        self.progress.reset("正在检测…")
        token = self._detect_token = self._detect_token + 1

        def done(detection: core.Detection) -> None:
            if token != self._detect_token:
                return
            self.detection = detection
            self._render_info()
            if detection.found:
                self.progress.reset("检测完成，可以提取")
                if not self.output_custom:
                    self.output_row.set(self._default_output(path, detection))
            else:
                self.progress.reset("没有检测到压缩包")

        def fail(exc: BaseException) -> None:
            if token != self._detect_token:
                return
            self.detection = core.Detection()
            self._render_info()
            self.progress.reset("检测失败")
            self.app.logbook.log("检测失败", exc)

        self.app.run_bg(lambda: core.detect_archive(path), done, fail, label="detect")

    def _render_info(self) -> None:
        detection = self.detection
        if not detection.found:
            for label in self.info_labels.values():
                label.configure(text="—", text_color=c("faint"))
            return
        total = 0
        try:
            total = os.path.getsize(self.drop.path)
        except OSError:
            pass
        size = max(0, total - detection.offset)
        self.info_labels["kind"].configure(
            text={"zip": "ZIP", "rar": "RAR", "7z": "7Z"}.get(detection.kind, detection.kind.upper()),
            text_color=c("text"),
        )
        self.info_labels["size"].configure(text=core.human_size(size), text_color=c("text"))
        self.info_labels["offset"].configure(text=f"{detection.offset:,} 字节", text_color=c("text"))
        self.info_labels["valid"].configure(
            text="通过" if detection.valid else "未完全校验",
            text_color=c("success") if detection.valid else c("warning"),
        )

    def _default_output(self, path: str, detection: core.Detection) -> str:
        stem = os.path.splitext(path)[0]
        if stem.endswith("_hidden") and len(os.path.basename(stem)) > len("_hidden"):
            stem = stem[: -len("_hidden")]
        return f"{stem}.{detection.ext or 'zip'}"

    def choose_output(self) -> None:
        current = self.output_row.get() or self._default_output(self.drop.path, self.detection)
        extension = os.path.splitext(current)[1] or ".zip"
        path = filedialog.asksaveasfilename(
            title="选择压缩包保存位置",
            initialdir=os.path.dirname(current),
            initialfile=os.path.basename(current),
            defaultextension=extension,
            filetypes=[("压缩包", f"*{extension}"), ("所有文件", "*.*")],
        )
        if path:
            self.output_custom = True
            self.output_row.set(path)

    # -- 鎻愬彇 --------------------------------------------------------------- #
    def start(self) -> None:
        if self.app.busy:
            return
        image = self.drop.path
        if not image or not os.path.isfile(image):
            Dialog(self.app, title="还没选图片", message="请先选择被隐藏过的图片。", kind="warning")
            return
        if not self.detection.found:
            Dialog(
                self.app, title="没检测到压缩包",
                message="这张图片尾部没有找到 ZIP / RAR / 7Z 结构，可能不是隐藏图，或文件已被修改。",
                kind="warning",
            )
            return

        output = self.output_row.get() or self._default_output(image, self.detection)
        self.output_row.set(output)
        if core.same_path(output, image):
            Dialog(self.app, title="保存位置冲突", message="输出文件不能和原图片相同。", kind="error")
            return
        folder = os.path.dirname(os.path.abspath(output)) or "."
        if not os.path.isdir(folder):
            Dialog(self.app, title="保存文件夹不存在", message=f"找不到文件夹：\n{folder}", kind="error")
            return

        if os.path.exists(output) and not self.app.settings.get("auto_overwrite", False):
            def do_confirm() -> None:
                self._launch(image, output)

            Dialog(
                self.app, title="文件已存在",
                message=f"已有同名文件：\n{os.path.basename(output)}\n要覆盖它吗？",
                kind="warning",
                buttons=[("覆盖", do_confirm), ("取消", None)],
            )
            return

        self._launch(image, output)

    def _launch(self, image: str, output: str) -> None:
        size = max(0, os.path.getsize(image) - self.detection.offset)
        self.result.grid_remove()
        self.app.set_busy(True, "正在提取…")
        self.progress.reset("准备中…")
        self.progress.begin(size)
        self.app.logbook.log(f"开始提取：{os.path.basename(image)} → {os.path.basename(output)}")

        def work():
            return core.extract_archive(
                image, output, detection=self.detection, overwrite=True,
                progress=lambda fraction, text: self.app.post_progress(self.progress, fraction, text),
                cancel_event=self.app.cancel_event,
            )

        def done(result) -> None:
            self.app.set_busy(False)
            self.progress.finish("提取完成")
            self._last_output = result.output
            detail = [f"已取出 {core.human_size(result.size)} 的 {result.ext.upper()}",
                      f"耗时 {core.human_duration(result.elapsed)}"]
            if result.verified:
                detail.append("SHA-256 校验通过")
            self.result_label.configure(text=" · ".join(detail))
            self.result.grid()
            self.app.logbook.log(f"提取成功：{result.output}（{core.human_size(result.size)}）")
            self.app.toast("提取完成", "success")

        def fail(exc: BaseException) -> None:
            self.app.set_busy(False)
            if isinstance(exc, core.OperationCancelled):
                self.progress.reset("已取消")
                self.app.toast("已取消", "info")
                self.app.logbook.log("提取已取消")
                return
            self.progress.reset("失败")
            self.app.logbook.log("提取失败", exc)
            Dialog(
                self.app, title="提取失败", message=str(exc) or exc.__class__.__name__,
                detail=traceback.format_exc(limit=3), kind="error",
            )

        self.app.run_bg(work, done, fail, label="extract")

    def _open_output(self) -> None:
        if self._last_output:
            core.open_folder(os.path.dirname(self._last_output))

    def _copy_output(self) -> None:
        if not self._last_output:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._last_output)
            self.app.toast("路径已复制", "success")
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- #
# 批量页
# --------------------------------------------------------------------------- #
class BatchPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(
            master, fg_color="transparent",
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.app = app
        self.archives: list[str] = []
        self.cover = ""
        self._rows: list[dict] = []
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        PageTitle(
            self, "批量隐藏", "一张封面图，依次藏入多个压缩包，各自生成一张隐藏图",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # 封面
        cover_card = Card(self)
        cover_card.grid(row=1, column=0, sticky="ew")
        cover_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            cover_card, text="封面图片", font=font(13, "bold"), text_color=c("text"),
        ).grid(row=0, column=0, sticky="w", padx=(16, 10), pady=14)
        self.cover_label = ctk.CTkLabel(
            cover_card, text="未选择", font=font(12), text_color=c("muted"), anchor="w",
        )
        self.cover_label.grid(row=0, column=1, sticky="ew", pady=14)
        GhostButton(cover_card, text="选择", width=72, height=32, command=self.choose_cover).grid(
            row=0, column=2, padx=(8, 16)
        )

        # 鍒楄〃
        list_card = Card(self)
        list_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        list_card.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(list_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="压缩包列表", font=font(13, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.count_label = MutedLabel(header, "0 个", size=11)
        self.count_label.grid(row=0, column=1, sticky="e")

        self.list_frame = ctk.CTkScrollableFrame(
            list_card, height=196, fg_color=c("card_alt"), corner_radius=12,
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.list_frame.grid(row=1, column=0, sticky="ew", padx=16)
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.empty_label = MutedLabel(
            self.list_frame, "还没有添加压缩包，点下面的“添加压缩包”或把文件拖进窗口。", size=12,
        )
        self.empty_label.grid(row=0, column=0, sticky="w", padx=12, pady=14)

        buttons = ctk.CTkFrame(list_card, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 14))
        GhostButton(buttons, text="添加压缩包", width=110, height=32, command=self.add_archives).pack(side="left")
        GhostButton(buttons, text="清空列表", width=90, height=32, command=self.clear_archives).pack(
            side="left", padx=(8, 0)
        )

        # 输出目录
        out = Card(self)
        out.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        out.grid_columnconfigure(0, weight=1)
        out_inner = ctk.CTkFrame(out, fg_color="transparent")
        out_inner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        out_inner.grid_columnconfigure(0, weight=1)
        self.output_row = PathRow(out_inner, "输出到", self.choose_output_dir)
        self.output_row.grid(row=0, column=0, sticky="ew")
        MutedLabel(
            out_inner, "每张隐藏图命名为「封面名_压缩包名_hidden.png」", size=11,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        # 加密
        self.encrypt_var = tk.BooleanVar(value=False)
        self.encrypt_row = SwitchRow(
            out_inner, "AES-256 加密每个压缩包",
            "所有压缩包都使用同一个密码重新封装", self.encrypt_var,
        )
        self.encrypt_row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.password_entry = ctk.CTkEntry(
            out_inner, height=36, corner_radius=9, fg_color=c("card_alt"), border_width=1,
            border_color=c("border"), text_color=c("text"), font=font(12),
            placeholder_text="加密密码（至少 4 位）", show="●",
        )
        self.password_entry.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.password_entry.grid_remove()
        self.encrypt_var.trace_add("write", lambda *_: self._toggle_password())

        # 鎿嶄綔
        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        action.grid_columnconfigure(1, weight=1)
        self.start_btn = AccentButton(action, text="开始批量隐藏", width=168, height=46, command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="w")
        self.progress = ProgressPanel(action, self.app)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(18, 0))

        self.summary = MutedLabel(self, "", size=12)
        self.summary.grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.progress.reset("等待开始")

    def _toggle_password(self) -> None:
        if self.encrypt_var.get():
            self.password_entry.grid()
        else:
            self.password_entry.grid_remove()

    # -- 鍒楄〃缁存姢 ----------------------------------------------------------- #
    def choose_cover(self) -> None:
        path = filedialog.askopenfilename(
            title="选择封面图片",
            initialdir=self.app.settings.get("last_image_dir") or "",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            self.set_cover(path)

    def set_cover(self, path: str) -> None:
        self.cover = path
        try:
            size = core.human_size(os.path.getsize(path))
        except OSError:
            size = ""
        self.cover_label.configure(
            text=f"{shorten(os.path.basename(path), 40)}  ·  {size}", text_color=c("text")
        )
        self.app.settings.set("last_image_dir", os.path.dirname(path))

    def add_archives(self, paths: Optional[list[str]] = None) -> None:
        if paths is None:
            paths = list(filedialog.askopenfilenames(
                title="选择压缩包（可多选）",
                initialdir=self.app.settings.get("last_archive_dir") or "",
                filetypes=[("压缩包", "*.zip *.rar *.7z"), ("所有文件", "*.*")],
            ))
        added = 0
        known = {os.path.normcase(p) for p in self.archives}
        for path in paths:
            if not path or not os.path.isfile(path):
                continue
            if os.path.splitext(path)[1].lower() not in ARCHIVE_EXTS:
                continue
            if os.path.normcase(path) in known:
                continue
            known.add(os.path.normcase(path))
            self.archives.append(path)
            added += 1
        if added:
            self.app.settings.set("last_archive_dir", os.path.dirname(self.archives[-1]))
        self._refresh_list()
        if added:
            self.app.toast(f"已添加 {added} 个压缩包", "success")

    def clear_archives(self) -> None:
        self.archives.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self._rows = []
        self.count_label.configure(text=f"{len(self.archives)} 个")
        if not self.archives:
            self.empty_label = MutedLabel(
                self.list_frame, "还没有添加压缩包，点下面的“添加压缩包”或把文件拖进窗口。", size=12,
            )
            self.empty_label.grid(row=0, column=0, sticky="w", padx=12, pady=14)
            return

        for index, path in enumerate(self.archives):
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row, text=f"{index + 1:02d}", font=font(11), text_color=c("faint"), width=24,
            ).grid(row=0, column=0, sticky="w")
            name = ctk.CTkLabel(
                row, text=shorten(os.path.basename(path), 44), font=font(12),
                text_color=c("text"), anchor="w",
            )
            name.grid(row=0, column=1, sticky="ew", padx=(4, 8))
            try:
                size = core.human_size(os.path.getsize(path))
            except OSError:
                size = "—"
            status = ctk.CTkLabel(row, text=size, font=font(11), text_color=c("faint"), width=80, anchor="e")
            status.grid(row=0, column=2, sticky="e")
            remove = ctk.CTkButton(
                row, text="✕", width=24, height=24, corner_radius=6, fg_color="transparent",
                hover_color=c("card_hover"), text_color=c("faint"), font=font(11),
                command=lambda p=path: self._remove(p),
            )
            remove.grid(row=0, column=3, padx=(6, 0))
            self._rows.append({"path": path, "status": status, "size": size})

    def _remove(self, path: str) -> None:
        self.archives = [p for p in self.archives if p != path]
        self._refresh_list()

    def choose_output_dir(self) -> None:
        initial = self.output_row.get() or self.app.settings.get("default_output_dir") or ""
        path = filedialog.askdirectory(title="选择输出文件夹", initialdir=initial or None)
        if path:
            self.output_row.set(path)

    # -- 执行 --------------------------------------------------------------- #
    def start(self) -> None:
        if self.app.busy:
            return
        if not self.cover or not os.path.isfile(self.cover):
            Dialog(self.app, title="还没选封面图片", message="批量隐藏需要一张封面图片。", kind="warning")
            return
        if not self.archives:
            Dialog(self.app, title="列表是空的", message="请先添加至少一个压缩包。", kind="warning")
            return
        output_dir = self.output_row.get() or os.path.dirname(self.cover)
        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as exc:
                Dialog(self.app, title="无法创建输出文件夹", message=str(exc), kind="error")
                return
            self.output_row.set(output_dir)

        encrypt = bool(self.encrypt_var.get())
        password = self.password_entry.get() if encrypt else ""
        if encrypt and len(password) < 4:
            Dialog(self.app, title="密码太短", message="密码至少需要 4 位。", kind="warning")
            return

        archives = list(self.archives)
        total = 0
        for path in archives:
            try:
                total += os.path.getsize(self.cover) + os.path.getsize(path)
            except OSError:
                pass

        self.summary.configure(text="")
        self.app.set_busy(True, "正在批量隐藏…")
        self.progress.reset("准备中…")
        self.progress.begin(total)
        self.app.logbook.log(f"开始批量隐藏：{len(archives)} 个压缩包")

        def work():
            return core.batch_hide(
                self.cover, archives, output_dir,
                encrypt=encrypt, password=password, overwrite=True,
                verify=bool(self.app.settings.get("verify_after_hide", True)),
                progress=lambda fraction, text: self.app.post_progress(self.progress, fraction, text),
                cancel_event=self.app.cancel_event,
            )

        def done(result) -> None:
            self.app.set_busy(False)
            success = result.success_count
            failed = len(result.failed_items)
            self.progress.finish(f"完成 {success}/{len(result.items)}")
            self.summary.configure(
                text=f"成功 {success} 个" + (f"，失败 {failed} 个" if failed else "")
                + f"，总耗时 {core.human_duration(result.elapsed)}"
            )
            self._apply_statuses(result)
            if failed:
                detail = "\n".join(
                    f"{os.path.basename(item.archive)}：{item.error}" for item in result.failed_items
                )
                self.app.logbook.log(f"批量隐藏完成，失败 {failed} 个")
                Dialog(
                    self.app, title=f"{failed} 个文件失败",
                    message="其余文件已成功生成隐藏图。失败原因：", detail=detail, kind="warning",
                )
            else:
                self.app.logbook.log(f"批量隐藏全部成功：{success} 个")
                self.app.toast(f"已生成 {success} 张隐藏图", "success")

        def fail(exc: BaseException) -> None:
            self.app.set_busy(False)
            if isinstance(exc, core.OperationCancelled):
                self.progress.reset("已取消")
                self.app.toast("已取消", "info")
                self.app.logbook.log("批量隐藏已取消")
                return
            self.progress.reset("失败")
            self.app.logbook.log("批量隐藏失败", exc)
            Dialog(
                self.app, title="批量隐藏失败", message=str(exc) or exc.__class__.__name__,
                detail=traceback.format_exc(limit=3), kind="error",
            )

        self.app.run_bg(work, done, fail, label="batch")

    def _apply_statuses(self, result) -> None:
        by_path = {os.path.normcase(item.archive): item for item in result.items}
        for row in self._rows:
            item = by_path.get(os.path.normcase(row["path"]))
            if item is None:
                continue
            if item.ok:
                row["status"].configure(text="完成", text_color=c("success"))
            else:
                row["status"].configure(text="失败", text_color=c("danger"))


# --------------------------------------------------------------------------- #
# 设置页
# --------------------------------------------------------------------------- #
class SettingsPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(
            master, fg_color="transparent",
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.app = app
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        PageTitle(self, "设置", "所有修改会立即生效并自动保存").grid(
            row=0, column=0, sticky="ew", pady=(0, 12)
        )
        settings = self.app.settings

        # 外观
        look = self._section("外观", 1)
        self.accent_switch = ctk.CTkSegmentedButton(
            look, values=list(ACCENTS.keys()), font=font(12), height=32,
            selected_color=ac(self.app.accent), selected_hover_color=ac_hover(self.app.accent),
            unselected_color=c("card_alt"), unselected_hover_color=c("card_hover"),
            text_color=c("text"), fg_color=c("card_alt"),
            command=self._set_accent,
        )
        MutedLabel(look, "主题色", size=11).grid(row=0, column=0, sticky="w")
        self.accent_switch.grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.accent_switch.set(settings.get("theme", "蓝色") if settings.get("theme") in ACCENTS else "蓝色")

        mode_row = ctk.CTkFrame(look, fg_color="transparent")
        mode_row.grid(row=2, column=0, sticky="ew")
        mode_row.grid_columnconfigure(0, weight=1)
        MutedLabel(mode_row, "明暗模式", size=12).grid(row=0, column=0, sticky="w")
        self.mode_switch = ctk.CTkSegmentedButton(
            mode_row, values=["深色", "浅色", "跟随系统"], font=font(12), height=30, width=250,
            selected_color=ac(self.app.accent), selected_hover_color=ac_hover(self.app.accent),
            unselected_color=c("card_alt"), unselected_hover_color=c("card_hover"),
            text_color=c("text"), fg_color=c("card_alt"), command=self._set_mode,
        )
        current_mode = {"dark": "深色", "light": "浅色"}.get(settings.get("appearance_mode"), "跟随系统")
        self.mode_switch.set(current_mode)
        self.mode_switch.grid(row=0, column=1, sticky="e")

        # 行为
        behavior = self._section("行为", 2)
        behavior.grid_columnconfigure(0, weight=1)
        row = 0
        for key, title, description in [
            ("auto_open_folder", "完成后打开文件夹", "隐藏或提取成功后自动打开输出目录"),
            ("auto_overwrite", "自动覆盖同名文件", "遇到同名输出文件时不再询问"),
            ("verify_after_hide", "隐藏后校验", "重新检测并比对 SHA-256（更安全，稍慢一点）"),
            ("auto_check_update", "启动时检查更新", "在后台读取 GitHub 上的版本信息"),
            ("remember_window", "记住窗口位置", "下次启动时恢复窗口大小与位置"),
            ("remember_theme", "记住主题", "下次启动时沿用当前明暗模式与主题色"),
            ("confirm_close_while_busy", "任务中关闭前确认", "避免正在写入文件时误关窗口"),
        ]:
            variable = tk.BooleanVar(value=bool(settings.get(key)))
            switch_row = SwitchRow(
                behavior, title, description, variable,
                command=lambda k=key, v=variable: self._set_bool(k, v),
            )
            switch_row.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 10, 0))
            row += 1

        # 输出
        output = self._section("输出", 3)
        output.grid_columnconfigure(0, weight=1)
        mode_wrap = ctk.CTkFrame(output, fg_color="transparent")
        mode_wrap.grid(row=0, column=0, sticky="ew")
        mode_wrap.grid_columnconfigure(0, weight=1)
        MutedLabel(mode_wrap, "默认保存位置", size=12).grid(row=0, column=0, sticky="w")
        self.output_switch = ctk.CTkSegmentedButton(
            mode_wrap, values=["图片旁边", "指定文件夹"], font=font(12), height=30, width=200,
            selected_color=ac(self.app.accent), selected_hover_color=ac_hover(self.app.accent),
            unselected_color=c("card_alt"), unselected_hover_color=c("card_hover"),
            text_color=c("text"), fg_color=c("card_alt"), command=self._set_output_mode,
        )
        self.output_switch.set("指定文件夹" if settings.get("output_mode") == "custom" else "图片旁边")
        self.output_switch.grid(row=0, column=1, sticky="e")

        self.output_dir_row = PathRow(output, "文件夹", self._choose_output_dir)
        self.output_dir_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.output_dir_row.set(settings.get("default_output_dir") or "")
        if settings.get("output_mode") != "custom":
            self.output_dir_row.grid_remove()

        # 数据
        data = self._section("数据与日志", 4)
        data.grid_columnconfigure(0, weight=1)
        data_buttons = ctk.CTkFrame(data, fg_color="transparent")
        data_buttons.grid(row=0, column=0, sticky="w")
        GhostButton(data_buttons, text="查看日志", width=100, height=32, command=self.app.show_log_window).pack(side="left")
        GhostButton(data_buttons, text="导出日志", width=100, height=32, command=self.app.export_log).pack(side="left", padx=(8, 0))
        GhostButton(data_buttons, text="打开程序目录", width=120, height=32, command=lambda: core.open_folder(core.app_dir())).pack(side="left", padx=(8, 0))
        GhostButton(data_buttons, text="恢复默认设置", width=120, height=32, command=self._reset).pack(side="left", padx=(8, 0))

        MutedLabel(self, f"{APP_NAME} V{APP_VERSION} · 配置文件：{self.app.settings.path}", size=10).grid(
            row=5, column=0, sticky="w", pady=(14, 0)
        )

    def _section(self, title: str, row: int) -> ctk.CTkFrame:
        card = Card(self)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        inner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            inner, text=title, font=font(13, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        body.grid_columnconfigure(0, weight=1)
        return body

    def _set_accent(self, value: str) -> None:
        self.app.set_accent(value)

    def _set_mode(self, value: str) -> None:
        self.app.set_appearance({"深色": "dark", "浅色": "light"}.get(value, "system"))

    def _set_bool(self, key: str, variable) -> None:
        self.app.settings.set(key, bool(variable.get()))
        self.app.settings.save()
        if key == "remember_theme":
            pass

    def _set_output_mode(self, value: str) -> None:
        self.app.settings.set("output_mode", "custom" if value == "指定文件夹" else "same_folder")
        self.app.settings.save()
        if value == "指定文件夹":
            self.output_dir_row.grid()
        else:
            self.output_dir_row.grid_remove()

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(
            title="选择默认输出文件夹",
            initialdir=self.app.settings.get("default_output_dir") or None,
        )
        if path:
            self.output_dir_row.set(path)
            self.app.settings.update({"default_output_dir": path, "output_mode": "custom"})
            self.app.settings.save()
            self.output_switch.set("指定文件夹")
            self.output_dir_row.grid()

    def _reset(self) -> None:
        def do_reset() -> None:
            self.app.settings.reset()
            self.app.toast("已恢复默认设置", "success")
            self.app.rebuild_settings_page()

        Dialog(
            self.app, title="恢复默认设置",
            message="会重置主题、窗口位置与所有选项，但不会删除任何文件。",
            kind="warning", buttons=[("恢复默认", do_reset), ("取消", None)],
        )


# --------------------------------------------------------------------------- #
# 关于页
# --------------------------------------------------------------------------- #
class AboutPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(
            master, fg_color="transparent",
            scrollbar_button_color=c("border"), scrollbar_button_hover_color=c("card_hover"),
        )
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        PageTitle(self, "关于", f"{APP_NAME} V{APP_VERSION}").grid(row=0, column=0, sticky="ew", pady=(0, 12))

        intro = Card(self)
        intro.grid(row=1, column=0, sticky="ew")
        intro.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            intro, text="把文件藏进图片里", font=font(17, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            intro,
            text=(
                "HideZipImage 会把压缩包追加到图片文件末尾：图片仍然可以正常浏览，"
                "而压缩包完整地藏在后面。任何人都能用本程序把压缩包再取出来。\n\n"
                "这不是加密工具。文件尾部结构对了解格式的人来说是可见的，"
                "需要保密请勾选「AES-256 密码加密」或使用专门的加密软件。"
            ),
            font=font(12), text_color=c("muted"), anchor="w", justify="left", wraplength=680,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))

        features = Card(self)
        features.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        features.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            features, text="V3.1.0 更新", font=font(13, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        for index, line in enumerate([
            "全新侧边栏界面：隐藏 / 提取 / 批量 / 设置 各自独立",
            "检测算法重写：从 ZIP 目录尾部反推真实偏移，不再被图片像素里的假 PK 头骗到",
            "内存占用恒定：GB 级文件也只分块读写，不再整文件读入内存",
            "写入先落 .part 临时文件，成功后才替掉；失败或取消不会留下半个文件",
            "隐藏后自动重新检测 + SHA-256 校验，确认压缩包确实完整",
            "支持取消、实时速度与剩余时间，批量任务可逐个查看结果",
            "修复：检测失败后按钮永久卡死、输出路径与源文件相同时静默损坏原文件",
            "修复：设置文件并发写坏、窗口关闭时线程回调报错、更新检查卡住界面",
        ]):
            ctk.CTkLabel(
                features, text=f"·  {line}", font=font(12), text_color=c("muted"),
                anchor="w", justify="left", wraplength=680,
            ).grid(row=index + 1, column=0, sticky="w", padx=22, pady=(0, 4))
        ctk.CTkFrame(features, height=6, fg_color="transparent").grid(row=20, column=0)

        links = Card(self)
        links.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        links.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            links, text="链接", font=font(13, "bold"), text_color=c("text"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        row = ctk.CTkFrame(links, fg_color="transparent")
        row.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))
        GhostButton(row, text="GitHub 仓库", width=120, height=34, command=self._open_github).pack(side="left")
        GhostButton(row, text="检查更新", width=100, height=34, command=self.app.check_update_manual).pack(side="left", padx=(8, 0))
        GhostButton(row, text="问题反馈", width=100, height=34, command=self._open_issues).pack(side="left", padx=(8, 0))

        MutedLabel(
            self,
            "本程序按「现状」提供，作者不对使用造成的任何数据丢失或法律责任负责。"
            "请仅用于自己拥有合法权利的文件。",
            size=10,
        ).grid(row=4, column=0, sticky="w", pady=(14, 0))

    def _open_github(self) -> None:
        import webbrowser
        webbrowser.open(GITHUB_URL)

    def _open_issues(self) -> None:
        import webbrowser
        webbrowser.open(f"{GITHUB_URL}/issues")


# --------------------------------------------------------------------------- #
# 日志窗口
# --------------------------------------------------------------------------- #
class LogWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("运行日志")
        self.configure(fg_color=c("bg"))
        self.geometry("780x540")
        self.transient(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)
        MutedLabel(header, "最近 1000 条记录，导出时会附上程序版本与设置路径", size=11).grid(
            row=0, column=0, sticky="w"
        )
        GhostButton(header, text="刷新", width=70, height=30, command=self.refresh).grid(row=0, column=1)
        GhostButton(header, text="导出", width=70, height=30, command=app.export_log).grid(row=0, column=2, padx=(8, 0))
        GhostButton(header, text="清空", width=70, height=30, command=self._clear).grid(row=0, column=3, padx=(8, 0))

        self.text = ctk.CTkTextbox(
            self, corner_radius=12, fg_color=c("log_bg"), border_width=1, border_color=c("border"),
            text_color=c("text"), font=ctk.CTkFont(family="Consolas", size=12), wrap="none",
        )
        self.text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.refresh()
        self.update_idletasks()
        self._center()

    def _center(self) -> None:
        try:
            x = self.app.winfo_rootx() + (self.app.winfo_width() - 780) // 2
            y = self.app.winfo_rooty() + (self.app.winfo_height() - 540) // 3
            self.geometry(f"780x540+{x}+{y}")
        except tk.TclError:
            pass

    def refresh(self) -> None:
        lines = self.app.logbook.lines
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines) if lines else "暂无日志。")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _clear(self) -> None:
        self.app.logbook.clear()
        self.refresh()


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class App(TkinterDnD.Tk):
    NAV = [
        ("hide", "隐藏文件", "+"),
        ("extract", "提取文件", "↓"),
        ("batch", "批量隐藏", "▤"),
        ("settings", "设置", "⚙"),
        ("about", "关于", "ⓘ"),
    ]

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode(self._initial_mode())
        self.settings = core.SettingsStore(os.path.join(core.app_dir(), "settings.json"))
        ctk.set_appearance_mode(self.settings.get("appearance_mode", "dark"))
        self.logbook = core.LogBook(
            self.settings, os.path.join(core.app_dir(), "HideZipImage.log")
        )
        self.accent = self.settings.get("theme", "蓝色")
        if self.accent not in ACCENTS:
            self.accent = "蓝色"
        set_active_accent(self.accent)
        self.busy = False
        self.cancel_event = threading.Event()
        self.current_page = "hide"
        self.pages: dict[str, ctk.CTkScrollableFrame] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._log_window: Optional[LogWindow] = None
        self._progress_panel: Optional[ProgressPanel] = None

        self.title(f"{APP_NAME} V{APP_VERSION}")
        self._apply_window_bg()
        self.minsize(1020, 660)
        self._restore_geometry()
        self._set_icon()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_content()

        self.toast_widget = Toast(self)
        self.toast_widget.lift()
        self._register_root_drop()
        self._drain()
        self.logbook.log(f"启动 {APP_NAME} V{APP_VERSION}")

        if self.settings.get("auto_check_update"):
            self.after(1500, lambda: self._check_update(silent=True))

    # -- 外观 --------------------------------------------------------------- #
    def _initial_mode(self) -> str:
        return "dark"

    def _window_bg(self) -> str:
        mode = ctk.get_appearance_mode()
        return LIGHT["bg"] if mode.lower() == "light" else DARK["bg"]

    def _apply_window_bg(self) -> None:
        """根窗口不是 CTk 控件，直接走 Tcl 设置背景色。"""
        try:
            self.tk.call(self._w, "configure", "-bg", self._window_bg())
        except tk.TclError:
            pass

    def _set_icon(self) -> None:
        try:
            path = core.resource_path("icon.ico")
            if os.path.exists(path):
                self.iconbitmap(path)
        except Exception:
            pass

    def _restore_geometry(self) -> None:
        geometry = self.settings.get("window_geometry") or ""
        if self.settings.get("remember_window", True) and geometry and "x" in geometry:
            try:
                self.geometry(geometry)
                return
            except tk.TclError:
                pass
        self.geometry("1180x780")

    def set_appearance(self, mode: str) -> None:
        mode = mode if mode in ("dark", "light", "system") else "dark"
        self.settings.set("appearance_mode", mode)
        self.settings.save()
        ctk.set_appearance_mode(mode)
        self._apply_window_bg()

    def set_accent(self, name: str) -> None:
        if name not in ACCENTS or name == self.accent:
            return
        self.accent = name
        set_active_accent(name)
        if self.settings.get("remember_theme", True):
            self.settings.set("theme", name)
            self.settings.save()
        self._build_sidebar()
        self._build_content()
        self.toast_widget.lift()

    # -- 侧边栏 ------------------------------------------------------------- #
    def _build_sidebar(self) -> None:
        for child in self.grid_slaves():
            if getattr(child, "_is_sidebar", False):
                child.destroy()

        sidebar = ctk.CTkFrame(self, width=214, corner_radius=0, fg_color=c("sidebar"))
        sidebar._is_sidebar = True  # type: ignore[attr-defined]
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(9, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(20, 22))
        logo = ctk.CTkFrame(brand, width=38, height=38, corner_radius=11, fg_color=ac(self.accent))
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="H", font=font(18, "bold"), text_color="#FFFFFF").place(
            relx=0.5, rely=0.5, anchor="center"
        )
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            names, text="HideZipImage", font=font(14, "bold"), text_color=c("text"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            names, text=f"V{APP_VERSION}  ·  ZIP in Image", font=font(10), text_color=c("faint"), anchor="w",
        ).pack(anchor="w")

        self.nav_buttons = {}
        for index, (key, label, glyph) in enumerate(self.NAV):
            active = key == self.current_page
            button = ctk.CTkButton(
                sidebar, text=f"  {glyph}   {label}", anchor="w", height=42, corner_radius=10,
                font=font(13, "bold" if active else "normal"),
                fg_color=c("card") if active else "transparent",
                hover_color=c("card_hover"),
                text_color=ac(self.accent) if active else c("muted"),
                command=lambda k=key: self.show(k),
            )
            button.grid(row=index + 1, column=0, sticky="ew", padx=12, pady=2)
            self.nav_buttons[key] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=10, column=0, sticky="ew", padx=12, pady=(0, 16))
        ctk.CTkButton(
            footer, text="  日志", anchor="w", height=34, corner_radius=9, font=font(12),
            fg_color="transparent", hover_color=c("card_hover"), text_color=c("muted"),
            command=self.show_log_window,
        ).pack(fill="x")
        ctk.CTkButton(
            footer, text="  GitHub", anchor="w", height=34, corner_radius=9, font=font(12),
            fg_color="transparent", hover_color=c("card_hover"), text_color=c("muted"),
            command=self._open_github,
        ).pack(fill="x")
        MutedLabel(footer, f"V{APP_VERSION}", size=10).pack(anchor="w", padx=10, pady=(6, 0))

    def _open_github(self) -> None:
        import webbrowser
        webbrowser.open(GITHUB_URL)

    # -- 内容区 ------------------------------------------------------------- #
    def _build_content(self) -> None:
        for child in self.grid_slaves():
            if getattr(child, "_is_content", False):
                child.destroy()

        content = ctk.CTkFrame(self, fg_color=c("bg"), corner_radius=0)
        content._is_content = True  # type: ignore[attr-defined]
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self.pages = {
            "hide": HidePage(content, self),
            "extract": ExtractPage(content, self),
            "batch": BatchPage(content, self),
            "settings": SettingsPage(content, self),
            "about": AboutPage(content, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew", padx=26, pady=22)
            page.grid_remove()
        self.pages[self.current_page].grid()
        self._register_root_drop()

    def show(self, key: str) -> None:
        if key not in self.pages:
            return
        self.current_page = key
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                fg_color=c("card") if active else "transparent",
                text_color=ac(self.accent) if active else c("muted"),
                font=font(13, "bold" if active else "normal"),
            )

    def rebuild_settings_page(self) -> None:
        old = self.pages.get("settings")
        parent = old.master if old is not None else None
        if old is not None:
            old.destroy()
        if parent is not None:
            page = SettingsPage(parent, self)
            page.grid(row=0, column=0, sticky="nsew", padx=26, pady=22)
            self.pages["settings"] = page
            if self.current_page == "settings":
                page.grid()
            else:
                page.grid_remove()

    # -- 忙碌状态 ----------------------------------------------------------- #
    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        if busy:
            self.cancel_event.clear()
        for page in self.pages.values():
            for attribute in ("start_btn",):
                button = getattr(page, attribute, None)
                if button is not None:
                    try:
                        button.configure(state="disabled" if busy else "normal")
                    except tk.TclError:
                        pass
        if busy and message:
            self.logbook.log(message)

    def cancel_current(self) -> None:
        self.cancel_event.set()

    def run_bg(self, work: Callable[[], object], on_done, on_error, label: str = "task") -> None:
        def runner() -> None:
            try:
                result = work()
            except BaseException as exc:  # noqa: BLE001 - 全部交给 UI 呈现
                self._post(on_error, exc)
            else:
                self._post(on_done, result)

        threading.Thread(target=runner, daemon=True, name=f"hzi-{label}").start()

    def _post(self, callback, argument) -> None:
        self._queue.put((callback, argument))

    def post_progress(self, panel: ProgressPanel, fraction: float, text: str) -> None:
        self._queue.put((panel.set_progress, (fraction, text)))

    def _drain(self) -> None:
        while True:
            try:
                callback, argument = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if isinstance(argument, tuple):
                    callback(*argument)
                else:
                    callback(argument)
            except Exception:
                self.logbook.log("界面回调异常", Exception(traceback.format_exc(limit=3)))
        if self.winfo_exists():
            self.after(60, self._drain)

    # -- 浜や簰 --------------------------------------------------------------- #
    def toast(self, text: str, kind: str = "info") -> None:
        self.toast_widget.show(text, kind)

    def _register_root_drop(self) -> None:
        """窗口空白处也能接收拖拽（卡片内部有更具体的处理）。"""
        for widget in self.grid_slaves():
            if not getattr(widget, "_is_content", False):
                continue
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_root_drop)
            except Exception:
                pass

    def _on_root_drop(self, event) -> None:
        paths = core.clean_drop_path(getattr(event, "data", ""))
        self.handle_dropped(paths)

    def handle_dropped(self, paths: list[str], preferred: str = "") -> None:
        if self.busy or not paths:
            return
        images = [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_EXTS]
        archives = [p for p in paths if os.path.splitext(p)[1].lower() in ARCHIVE_EXTS]

        if self.current_page == "extract" and images:
            self.pages["extract"].set_path(images[0])
            return
        if self.current_page == "batch":
            batch = self.pages["batch"]
            if images and not batch.cover:
                batch.set_cover(images[0])
                images = images[1:]
            if archives:
                batch.add_archives(archives)
            return

        hide = self.pages["hide"]
        if preferred == "image" and images:
            hide.set_image(images[0])
            if archives:
                hide.set_archive(archives[0])
            return
        if preferred == "archive" and archives:
            hide.set_archive(archives[0])
            if images:
                hide.set_image(images[0])
            return
        if images and not hide.image_card.path:
            hide.set_image(images[0])
        if archives and not hide.archive_card.path:
            hide.set_archive(archives[0])
        if not images and not archives:
            self.toast("只支持图片（JPG/PNG/WEBP/BMP）和压缩包（ZIP/RAR/7Z）", "warning")

    def show_log_window(self) -> None:
        if self._log_window is not None and self._log_window.winfo_exists():
            self._log_window.refresh()
            self._log_window.lift()
            self._log_window.focus_force()
            return
        self._log_window = LogWindow(self)

    def export_log(self) -> None:
        path = filedialog.asksaveasfilename(
            title="导出日志",
            initialdir=self.settings.get("last_output_dir") or core.app_dir(),
            initialfile="HideZipImage_log.txt",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            self.logbook.export(path, extra={"设置文件": self.settings.path})
            self.toast("日志已导出", "success")
        except OSError as exc:
            Dialog(self, title="导出失败", message=str(exc), kind="error")

    # -- 鏇存柊 --------------------------------------------------------------- #
    def check_update_manual(self) -> None:
        self._check_update(silent=False)

    def _check_update(self, silent: bool) -> None:
        if self.busy:
            return

        def done(info: core.UpdateInfo) -> None:
            if info.error:
                if not silent:
                    Dialog(
                        self, title="检查更新失败",
                        message="没能读取版本信息，可能是网络问题。", detail=info.error, kind="error",
                    )
                return
            if info.has_update:
                self.logbook.log(f"发现新版本 {info.latest_version}")
                Dialog(
                    self, title=f"发现新版本 {info.latest_version}",
                    message=info.message or "有新的版本可以下载。",
                    kind="info",
                    buttons=[("打开发布页", lambda: self._open(info.download_url)), ("稍后", None)],
                )
            elif not silent:
                Dialog(
                    self, title="已经是最新版本",
                    message=f"当前版本 V{APP_VERSION} 已是最新。", kind="success",
                )

        def fail(exc: BaseException) -> None:
            if not silent:
                Dialog(self, title="检查更新失败", message=str(exc), kind="error")

        self.run_bg(lambda: core.fetch_update_info(8), done, fail, label="update")

    def _open(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    # -- 鍏抽棴 --------------------------------------------------------------- #
    def on_close(self) -> None:
        if self.busy and self.settings.get("confirm_close_while_busy", True):
            def force() -> None:
                self.cancel_event.set()
                self._shutdown()

            Dialog(
                self, title="任务进行中", message="正在写入文件，现在关闭可能留下未完成的临时文件。仍要关闭吗？",
                kind="warning", buttons=[("仍要关闭", force), ("缁х画绛夊緟", None)],
            )
            return
        self._shutdown()

    def _shutdown(self) -> None:
        try:
            if self.settings.get("remember_window", True):
                self.settings.set("window_geometry", self.geometry())
            self.settings.save()
        except Exception:
            pass
        self.cancel_event.set()
        try:
            self.destroy()
        except tk.TclError:
            pass


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()






