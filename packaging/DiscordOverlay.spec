# PyInstaller one-folder build. Run scripts/build_windows.ps1 rather than invoking this directly.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
assets = root / "discord_overlay" / "assets"
datas = [(str(path), "discord_overlay/assets") for path in assets.iterdir() if path.is_file()]
binaries = []
hiddenimports = []
for package in ("customtkinter", "rapidocr"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tests", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DiscordOverlay",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(assets / "icon.ico"),
)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="DiscordOverlay")
