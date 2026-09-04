"""Bundled alert tones and non-blocking sound playback."""
from __future__ import annotations

import math
import struct
import threading
import wave
from pathlib import Path

from .paths import sounds_dir

# name -> [(frequency Hz, seconds), ...]; frequency 0 is silence.
DEFAULT_SOUNDS: dict[str, list[tuple[int, float]]] = {
    "Alert": [(880, 0.11), (0, 0.04), (1175, 0.18)],
    "Warning": [(440, 0.18), (0, 0.06), (440, 0.18), (0, 0.06), (330, 0.24)],
    "Chime": [(660, 0.10), (880, 0.10), (1100, 0.22)],
    "Success": [(523, 0.10), (659, 0.10), (784, 0.22)],
    "Pulse": [(220, 0.09), (0, 0.05), (220, 0.09)],
}
SOUND_EXTENSIONS = {".wav", ".ogg", ".mp3"}
SAMPLE_RATE = 44_100


def ensure_default_sounds() -> dict[str, Path]:
    """Synthesize the bundled tones on first use and return name -> path."""
    directory = sounds_dir()
    directory.mkdir(parents=True, exist_ok=True)
    output: dict[str, Path] = {}
    for name, notes in DEFAULT_SOUNDS.items():
        path = directory / f"{name.casefold()}.wav"
        if not path.exists() or path.stat().st_size < 100:
            write_tone(path, notes)
        output[name] = path
    return output


def write_tone(path: Path, notes: list[tuple[int, float]], amplitude: int = 16_000) -> None:
    frames = bytearray()
    for frequency, duration in notes:
        count = int(SAMPLE_RATE * duration)
        fade = min(int(SAMPLE_RATE * 0.012), max(1, count // 3))
        for index in range(count):
            envelope = min(1.0, index / fade, (count - index) / fade)
            value = 0 if not frequency else int(
                amplitude * envelope * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
            )
            frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)


class SoundPlayer:
    """WAV/OGG/MP3 playback through pygame's mixer with a small decoded-sound cache."""

    CACHE_SIZE = 16

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sounds: dict[tuple[str, int], object] = {}
        self._ready = False

    def play(self, path: Path, volume: float = 1.0) -> None:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Sound file not found: {path}")
        with self._lock:
            import pygame

            if not self._ready:
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=512)
                self._ready = True
            key = (str(path), path.stat().st_mtime_ns)
            sound = self._sounds.get(key)
            if sound is None:
                sound = pygame.mixer.Sound(str(path))
                self._sounds[key] = sound
                while len(self._sounds) > self.CACHE_SIZE:
                    self._sounds.pop(next(iter(self._sounds)))
            sound.set_volume(max(0.0, min(1.0, float(volume))))
            sound.play()

    def close(self) -> None:
        with self._lock:
            if not self._ready:
                return
            try:
                import pygame

                pygame.mixer.quit()
            finally:
                self._ready = False
                self._sounds.clear()
