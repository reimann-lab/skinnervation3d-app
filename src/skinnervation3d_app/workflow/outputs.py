from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

def extract_output_paths( 
    out: Any
) -> Optional[list[Path]]:
    """
    Extract output zarr_url(s) from a task return.

    Matches current Fractal task convention:
      out = {"image_list_updates": [{"zarr_url": "..."} , ...]}

    Return:
      list[Path] if found, otherwise None
    """
    try:
        if isinstance(out, dict):
            image_list_updated = out.get("image_list_updates", None)
            if image_list_updated is not None and isinstance(image_list_updated, list):
                image_list = []
                for image_dict in image_list_updated:
                    if "zarr_url" in image_dict.keys():
                        image_list.append(Path(image_dict["zarr_url"]))
                return image_list
    except Exception:
        return None
    return None