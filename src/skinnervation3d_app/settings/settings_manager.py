from __future__ import annotations

from pathlib import Path
from platformdirs import user_data_path

APP_NAME = "Skinnervation3D"         # shown in folder paths
APP_AUTHOR = "Skinnervation3D"       # mainly matters on Windows
DEFAULTS_PKG = "skinnervation3d-app"
DEFAULTS_SUBDIR = "settings"


def get_writable_channel_settings_dir() -> Path:
    
    # Put editable JSON presets in user DATA
    data_dir = user_data_path(APP_NAME, appauthor=APP_AUTHOR)
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / DEFAULTS_PKG / DEFAULTS_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p
