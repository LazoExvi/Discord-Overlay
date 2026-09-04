"""Pick the ONNX Runtime package that matches the installed graphics adapter.

The three onnxruntime distributions (CPU, CUDA, DirectML) share one module name
and must not be mixed in a single environment, so ``run.bat`` asks this module
which one to install. It is also importable without any third-party packages.
"""
from __future__ import annotations

import subprocess
import sys

NVIDIA_TOKENS = ("nvidia", "geforce", "quadro", " rtx")
AMD_TOKENS = ("amd", "radeon", "ati ", "advanced micro devices")
INTEL_TOKENS = ("intel", "arc graphics", "iris", "uhd graphics")


def classify_gpu(names: list[str]) -> str:
    """Return ``nvidia``, ``directml``, or ``cpu`` for the given adapter names."""
    normalized = "\n".join(names).casefold()
    if any(token in normalized for token in NVIDIA_TOKENS):
        return "nvidia"
    if any(token in normalized for token in AMD_TOKENS + INTEL_TOKENS):
        return "directml"
    return "cpu"


def detect_gpu_names() -> list[str]:
    """Read Windows display-adapter names through PowerShell; empty elsewhere."""
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            [
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            capture_output=True, text=True, timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def detected_backend() -> str:
    return classify_gpu(detect_gpu_names())


if __name__ == "__main__":
    print(detected_backend())
