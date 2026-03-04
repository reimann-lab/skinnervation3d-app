from __future__ import annotations

from pathlib import Path
from platformdirs import user_data_path
import shutil
from importlib import resources

APP_NAME = "Skinnervation3D"         # shown in folder paths
APP_AUTHOR = "Skinnervation3D"       # mainly matters on Windows
DEFAULTS_PKG = "mesospim_fractal_tasks"
DEFAULTS_SUBDIR = "settings"


def get_writable_channel_settings_dir() -> Path:
    
    # Put editable JSON presets in user DATA
    data_dir = user_data_path(APP_NAME, appauthor=APP_AUTHOR)
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "mesospim-fractal-tasks" / "settings"
    p.mkdir(parents=True, exist_ok=True)
    return p

def ensure_default_channel_presets_copied() -> Path:
    """
    Copies packaged default JSON presets to user-writable settings dir,
    but does NOT overwrite existing user files.
    Returns the writable directory path.
    """
    dst_dir = get_writable_channel_settings_dir()

    # packaged_dir is a Traversable (not always a real Path)
    packaged_dir = resources.files(DEFAULTS_PKG) / DEFAULTS_SUBDIR

    # Iterate resources and copy any channel_color_*.json into dst_dir
    for res in packaged_dir.iterdir():
        if not res.is_file():
            continue
        name = res.name
        if not (name.startswith("channel_color_") and name.endswith(".json")):
            continue

        dst = dst_dir / name
        if dst.exists():
            continue  # don't overwrite user edits

        # Convert resource to a real filesystem path when necessary
        with resources.as_file(res) as src_path:
            shutil.copyfile(src_path, dst)

    return dst_dir