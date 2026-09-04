"""Process entry point."""
from __future__ import annotations

import ctypes
import os

from .diagnostics import configure_crash_logging

APP_USER_MODEL_ID = "DiscordOverlay.DiscordOverlay.1"


def main() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    configure_crash_logging()
    from .ui import theme
    from .ui.main_window import App

    theme.apply_theme()
    App().mainloop()


if __name__ == "__main__":
    main()
