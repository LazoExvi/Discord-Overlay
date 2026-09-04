"""Palette, widget style presets, and small window helpers shared by every screen.

Discord-inspired dark theme: near-black ground, layered slate panels with hairline
borders, blurple accent, and warm/cool status colors for damage, healing, incoming.
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from importlib import resources

import customtkinter as ctk

from ..diagnostics import LOGGER_NAME

BG = "#0b0d12"
BG_DEEP = "#07080c"        # also the overlay's transparent key color
PANEL = "#12151c"
PANEL_2 = "#181c26"
PANEL_3 = "#1f2431"
INPUT_BG = "#0d1017"
BORDER = "#252b3a"
TEXT = "#e9ecf3"
MUTED = "#8b93a7"
DIM = "#5c647a"
ACCENT = "#7b8cff"         # blurple, lightened for text on dark
ACCENT_DEEP = "#5865f2"
GREEN = "#3ddc97"
RED = "#ff5c7a"
PURPLE = "#c084fc"
AMBER = "#f5a524"
CYAN = "#38d6ff"
SLATE = "#8ea2c2"

DAMAGE_OUT_COLOR = AMBER
DAMAGE_IN_COLOR = RED
HEAL_COLOR = GREEN
ACTOR_TYPE_COLORS = {
    "PLAYER": ACCENT_DEEP, "PET": CYAN, "OTHER": "#4a5878", "ENEMY": "#b0384f", "DAMAGE SHIELD": "#b57d1c",
}

ACCENT_BUTTON = dict(fg_color=ACCENT_DEEP, hover_color="#6b78ff")
QUIET_BUTTON = dict(fg_color=PANEL_2, hover_color="#222838")
STEEL_BUTTON = dict(fg_color="#232a3a", hover_color="#2d3648")
DANGER_BUTTON = dict(fg_color="#4a2230", hover_color="#612b3d")
START_BUTTON = dict(fg_color="#22995f", hover_color="#2bb673")
STOP_BUTTON = dict(fg_color="#8a3546", hover_color="#a13f54")
DISABLED_BUTTON = dict(fg_color="#2a3040", hover_color="#2a3040")
MENU = dict(fg_color="#232a3a", button_color="#2d3648", button_hover_color="#38425a", dropdown_fg_color=PANEL_3)
CHECKBOX = dict(fg_color=ACCENT_DEEP, hover_color="#6b78ff", border_color="#3a4358")
SEGMENT = dict(selected_color=ACCENT_DEEP, selected_hover_color="#6b78ff", unselected_color="#232a3a",
               unselected_hover_color="#2d3648")
TEXTBOX = dict(fg_color=INPUT_BG, border_width=1, border_color=BORDER, text_color=TEXT)
CARD = dict(fg_color=PANEL_2, corner_radius=12, border_width=1, border_color=BORDER)

DISPLAY_FAMILY = "Bahnschrift"   # ships with Windows 10+; Tk falls back silently elsewhere
NUMBER_FAMILY = "Bahnschrift"


def apply_theme() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def font(size: int = 13, bold: bool = False, family: str | None = None) -> ctk.CTkFont:
    kwargs = {"size": size, "weight": "bold" if bold else "normal"}
    if family:
        kwargs["family"] = family
    return ctk.CTkFont(**kwargs)


def display_font(size: int, bold: bool = True) -> ctk.CTkFont:
    return font(size, bold, DISPLAY_FAMILY)


def number_font(size: int, bold: bool = True) -> ctk.CTkFont:
    return font(size, bold, NUMBER_FAMILY)


def heading(parent, text: str, size: int = 20, color: str = ACCENT) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=color, font=display_font(size), anchor="w")


def note(parent, text: str, wraplength: int = 640, color: str = MUTED) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=color, anchor="w", justify="left", wraplength=wraplength)


def card(parent, **overrides) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, **{**CARD, **overrides})


def icon_image(size: int = 28) -> ctk.CTkImage | None:
    try:
        from PIL import Image

        assets = resources.files("discord_overlay").joinpath("assets")
        with resources.as_file(assets.joinpath("icon.png")) as png_path:
            image = Image.open(png_path).convert("RGBA")
        return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
    except (OSError, ImportError):
        return None


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


def blend(color: str, target: str, amount: float) -> str:
    """Mix two #RRGGBB colors; ``amount`` 0 returns ``color``, 1 returns ``target``."""
    c = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    t = [int(target[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a + (b - a) * amount):02x}" for a, b in zip(c, t))
