from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from typing import List
from skinnervation3d_app.config import CONDA_NAPARI_ENV_NAME, CONDA_NAPARI_ENV_ROOT

def launch_napari_in_conda_env(
    *, 
    analysis_dir: Path, 
    zarr_paths: List[str] | None
) -> None:
    
    child_env = os.environ.copy()
    child_env.pop("QT_API", None)

    if sys.platform == "win32":
        env_root = CONDA_NAPARI_ENV_ROOT
        python_exe = env_root / "pythonw.exe"
        scripts_dir = env_root / "Scripts"
        lib_dir = env_root / "Library" / "bin"
        args = [str(python_exe), "-m", "napari"]

        prepend = [str(env_root), str(scripts_dir)]
        if lib_dir.exists():
            prepend.append(str(lib_dir))
        child_env["PATH"] = os.pathsep.join(prepend + [child_env.get("PATH", "")])
    elif sys.platform == "darwin":
        args = ["conda", "run", "-n", CONDA_NAPARI_ENV_NAME, "napari"]
    elif sys.platform == "linux":
        args = ["conda", "run", "-n", CONDA_NAPARI_ENV_NAME, "napari"]
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
    if zarr_paths:
        for p in zarr_paths:
            args.append(str(p))

    p = subprocess.Popen(
        args,
        cwd=str(analysis_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
        env=child_env,
    )