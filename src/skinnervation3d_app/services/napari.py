from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import List
from skinnervation3d_app.config import CONDA_NAPARI_ENV_NAME

def launch_napari_in_conda_env(
    *, 
    analysis_dir: Path, 
    zarr_paths: List[str] | None
) -> None:

    #log_path = analysis_dir / f"napari_launch.log"
    child_env = os.environ.copy()
    child_env.pop("QT_API", None)
    args = ["conda", "run", "-n", CONDA_NAPARI_ENV_NAME, "napari"]
    if zarr_paths:
        for p in zarr_paths:
            args.append(str(p))

    #with log_path.open("w") as f:
    #    f.write("CMD: " + " ".join(args) + "\n\n")
    p = subprocess.Popen(
        args,
        cwd=str(analysis_dir),
        stdout=subprocess.DEVNULL, #f
        stderr=subprocess.STDOUT,
        text=True,
        env=child_env,
    )
     #   f.write(f"\nSpawned PID: {p.pid}\n")