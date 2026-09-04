"""Queued Windows text-to-speech through System.Speech; a no-op elsewhere."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass

_ENV_TEXT = "DISCORD_OVERLAY_SPEECH_TEXT"
_ENV_VOICE = "DISCORD_OVERLAY_SPEECH_VOICE"
_ENV_RATE = "DISCORD_OVERLAY_SPEECH_RATE"
_ENV_VOLUME = "DISCORD_OVERLAY_SPEECH_VOLUME"
_POWERSHELL = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
_SPEAK_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    f"$v=$env:{_ENV_VOICE}; if($v){{try{{$s.SelectVoice($v)}}catch{{}}}}; "
    f"$s.Rate=[int]$env:{_ENV_RATE}; $s.Volume=[int]$env:{_ENV_VOLUME}; "
    f"$s.Speak($env:{_ENV_TEXT})"
)
_VOICES_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.GetInstalledVoices() | ForEach-Object {$_.VoiceInfo.Name}"
)


@dataclass(slots=True)
class SpeechRequest:
    text: str
    voice: str = ""
    rate: int = 0
    volume: int = 100


def installed_voices() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            [*_POWERSHELL, _VOICES_SCRIPT], capture_output=True, text=True, timeout=10,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class SpeechPlayer:
    """Speak messages in order, or interrupt the current one when asked."""

    def __init__(self) -> None:
        self._queue: queue.Queue[SpeechRequest | None] = queue.Queue()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="speech-player", daemon=True)
        self._thread.start()

    def speak(self, text: str, voice: str = "", rate: int = 0, volume: int = 100,
              interrupt: bool = False) -> None:
        text = " ".join(text.split()).strip()
        if not text or self._closed or sys.platform != "win32":
            return
        if interrupt:
            self._clear_pending()
            self._terminate_current()
        self._queue.put(SpeechRequest(
            text=text, voice=voice, rate=max(-10, min(10, int(rate))),
            volume=max(0, min(100, int(volume))),
        ))

    def close(self) -> None:
        self._closed = True
        self._clear_pending()
        self._terminate_current()
        self._queue.put(None)

    def _clear_pending(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def _terminate_current(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                return
            env = os.environ.copy()
            env.update({
                _ENV_TEXT: request.text, _ENV_VOICE: request.voice,
                _ENV_RATE: str(request.rate), _ENV_VOLUME: str(request.volume),
            })
            try:
                process = subprocess.Popen(
                    [*_POWERSHELL, _SPEAK_SCRIPT], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                with self._lock:
                    self._process = process
                process.wait()
            except OSError:
                pass
            finally:
                with self._lock:
                    self._process = None
