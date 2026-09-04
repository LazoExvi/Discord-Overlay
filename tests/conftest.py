from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app_data(monkeypatch, tmp_path):
    """Point %LOCALAPPDATA% at a scratch directory so tests never touch real settings."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path
