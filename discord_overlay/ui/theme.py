"""Palette, widget style presets, and small window helpers shared by every screen."""
from __future__ import annotations

import logging
import os
import tkinter as tk
from importlib import resources

import customtkinter as ctk

from ..diagnostics import LOGGER_NAME

BG = "#0b1118"
BG_DEEP = "#080d12"
PANEL = "#121b25"
PANEL_2 = "#172330"
INPUT_BG = "#0a1017"
BORDER = "#2c4054"
TEXT = "#e7edf4"
MUTED = "#8fa1b3"
DIM = "#657789"
ACCENT = "#d39b47"
GREEN = "#42d392"
RED = "#ff6577"
PURPLE = "#ad7bff"

ACCENT_BUTTON = dict(fg_color="#b77a2d", hover_color="#d08c35")
QUIET_BUTTON = dict(fg_color=PANEL_2, hover_color="#223448")
STEEL_BUTTON = dict(fg_color="#263a4e", hover_color="#304a64")
DANGER_BUTTON = dict(fg_color="#522b32", hover_color="#683740")
START_BUTTON = dict(fg_color="#277a55", hover_color="#32966a")
STOP_BUTTON = dict(fg_color="#753a43", hover_color="#914752")
DISABLED_BUTTON = dict(fg_color="#394653", hover_color="#394653")
MENU = dict(fg_color="#263a4e", button_color="#304a64", dropdown_fg_color=PANEL_2)
CHECKBOX = dict(fg_color="#b77a2d", hover_color="#d08c35")
SEGMENT = dict(selected_color="#a66e29", selected_hover_color="#bd7e2e")
TEXTBOX = dict(fg_color=INPUT_BG, border_width=1, border_color=BORDER, text_color=TEXT)


def apply_theme() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def font(size: int = 13, bold: bool = False, family: str | None = None) -> ctk.CTkFont:
    kwargs = {"size": size, "weight": "bold" if bold else "normal"}
    if family:
        kwargs["family"] = family
    return ctk.CTkFont(**kwargs)


def heading(parent, text: str, size: int = 20, color: str = ACCENT) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=color, font=font(size, bold=True), anchor="w")


def note(parent, text: str, wraplength: int = 640, color: str = MUTED) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=color, anchor="w", justify="left", wraplength=wraplength)


def apply_window_icon(window: tk.Misc) -> None:
    """Apply the packaged icon while keeping the Tk photo reference alive."""
    try:
        from PIL import Image, ImageTk

        assets = resources.files("discord_overlay").joinpath("assets")
        with resources.as_file(assets.joinpath("icon.png")) as png_path:
            photo = ImageTk.PhotoImage(Image.open(png_path).convert("RGBA"))
            window.iconphoto(True, photo)
            window._discord_overlay_icon = photo  # type: ignore[attr-defined]
        if os.name == "nt":
            with resources.as_file(assets.joinpath("icon.ico")) as ico_path:
                window.iconbitmap(default=str(ico_path))
    except (OSError, tk.TclError, ImportError):
        logging.getLogger(LOGGER_NAME).warning("Unable to apply application icon", exc_info=True)


def release_grab(window: tk.Misc) -> None:
    try:
        window.grab_release()
    except tk.TclError:
        pass


def bring_to_front(window: tk.Misc, grab: bool = False) -> None:
    try:
        if not window.winfo_exists():
            return
        window.lift()
        window.focus_force()
        if grab:
            window.after(100, window.grab_set)
    except tk.TclError:
        pass
