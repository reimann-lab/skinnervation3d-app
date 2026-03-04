from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator


class ChannelEntry(BaseModel):
    label: str
    color: str = Field(default="FFFFFF")           # default white
    dye_wavelength: str = Field(default="NaN")
    laser_wavelength: str

    @field_validator("label")
    @classmethod
    def _label_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("label is required")
        return v

    @field_validator("laser_wavelength")
    @classmethod
    def _laser_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("laser_wavelength is required")
        return v

    @field_validator("color")
    @classmethod
    def _color_hex6(cls, v: str) -> str:
        v = (v or "").strip().lstrip("#").upper()
        if len(v) != 6 or any(c not in "0123456789ABCDEF" for c in v):
            raise ValueError("color must be 6-digit hex like '00C853'")
        return v


# File schema: { "<laser>": { ...ChannelEntry... }, ... }
ChannelSettingsMap = Dict[str, ChannelEntry]