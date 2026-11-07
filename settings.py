"""
Snowcat's settings: what can be changed, the defaults, and saving them.

Each setting writes straight into the constant it controls in the snow
modules, so a change shows up on the very next frame. Choices are saved to
settings.json next to this file.
"""

import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

import cursorsnow
import snowballs
import snowcover
import snowfall

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

SECTIONS = ("Snowfall", "Piling up", "Playing with snow")


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    label: str
    help: str
    default: object               # bool for an on/off switch, a number for a slider
    module: object                # where the constant lives...
    attr: str                     # ...and its name
    low: float = 0
    high: float = 1
    step: float = 1
    unit: str = ""                # "%", "x" or "px": how the value is shown
    to_module: Optional[Callable] = None  # converts the shown value to the constant, if they differ
    requires: Optional[str] = None        # an on/off setting this one only matters with

    @property
    def is_switch(self):
        return isinstance(self.default, bool)

    def describe(self, value):
        """The value as shown next to its slider."""
        if self.unit == "%":
            return f"{round(value * 100)}%"
        if self.unit == "x":
            return f"{value:.1f}×"
        if self.unit == "px":
            return f"{value:.0f} px"
        return f"{value:g}"


SETTINGS = [
    # Snowfall
    Setting("amount", "Snowfall", "Amount of snow", "How many flakes are falling at once.",
            110, snowfall, "FLAKES_PER_MEGAPIXEL", 20, 300, 5),
    Setting("fall_speed", "Snowfall", "Fall speed", "How fast the flakes drift down.",
            1.0, snowfall, "FALL_SPEED_SCALE", 0.3, 2.5, 0.1, "x"),
    Setting("wind", "Snowfall", "Wind", "How strongly the breeze pushes the snow sideways.",
            1.0, snowfall, "WIND_SCALE", 0.0, 4.0, 0.1, "x"),

    # Piling up
    Setting("window_stick", "Piling up", "Snow sticking to windows",
            "Share of flakes that settle when they touch a window. The rest fall past in front.",
            0.5, snowcover, "WINDOW_STICK_CHANCE", 0.0, 1.0, 0.05, "%"),
    Setting("buildup", "Piling up", "Build-up speed", "How much snow each settled flake adds.",
            150, snowcover, "SNOW_PER_FLAKE", 20, 300, 10),
    Setting("window_depth", "Piling up", "Deepest snow on windows", "How tall a window's pile can get.",
            20, snowcover, "WINDOW_SNOW_DEPTH", 6, 40, 1, "px"),
    Setting("taskbar_stick", "Piling up", "Snow sticking to the taskbar",
            "Share of flakes that settle when they reach the taskbar.",
            1.0, snowcover, "TASKBAR_STICK_CHANCE", 0.0, 1.0, 0.05, "%"),
    Setting("taskbar_depth", "Piling up", "Deepest snow on the taskbar", "How tall the taskbar's pile can get.",
            40, snowcover, "TASKBAR_SNOW_DEPTH", 10, 80, 1, "px"),
    Setting("icons", "Piling up", "Snow on desktop icons", "Snow settles on top of your shortcut icons.",
            True, snowcover, "ICONS_ENABLED"),
    Setting("icon_depth", "Piling up", "Deepest snow on icons", "How tall the snow on an icon can get.",
            12, snowcover, "ICON_SNOW_DEPTH", 4, 30, 1, "px", requires="icons"),

    # Playing with snow
    Setting("shake", "Playing with snow", "Shake sensitivity",
            "How easily shaking a window knocks its snow off. Higher means a smaller shake is enough.",
            6, snowcover, "SHAKE_SWING", 1, 10, 1, to_module=lambda s: 168 / s),
    Setting("melt", "Playing with snow", "Hover to clear", "Moving the mouse onto a pile clears a circle around it.",
            True, snowcover, "MELT_ENABLED"),
    Setting("melt_size", "Playing with snow", "Circle size", "How big the cleared circle around the mouse is.",
            34, snowcover, "MELT_RADIUS", 10, 80, 2, "px", requires="melt"),
    Setting("gusts", "Playing with snow", "Mouse gusts", "Swiping the mouse fast blows the falling flakes around.",
            True, snowfall, "GUSTS_ENABLED"),
    Setting("hat", "Playing with snow", "Snow hat on the mouse",
            "Leave the mouse still and snow piles up on the pointer.",
            True, cursorsnow, "HAT_ENABLED"),
    Setting("slingshot", "Playing with snow", "Snowball slingshot",
            "Left-drag on the desktop, or right-drag anywhere (even over apps), then let go to fling a snowball.",
            True, snowballs, "SLINGSHOT_ENABLED"),
    Setting("throw", "Playing with snow", "Throwing power", "How fast snowballs fly for the same pull.",
            5.5, snowballs, "LAUNCH_POWER", 2.0, 10.0, 0.5, requires="slingshot"),
    Setting("blast", "Playing with snow", "Burst size", "How much snow a snowball knocks loose.",
            130, snowballs, "BLAST_RADIUS", 50, 300, 10, "px", requires="slingshot"),
]

BY_KEY = {setting.key: setting for setting in SETTINGS}


class Settings:
    """The current values, kept in sync with the snow modules and settings.json."""

    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self.values = {s.key: s.default for s in SETTINGS}
        self._load()

    def get(self, key):
        return self.values[key]

    def set(self, key, value):
        self.values[key] = value
        self._apply(BY_KEY[key])

    def reset(self):
        """Back to the defaults."""
        self.values = {s.key: s.default for s in SETTINGS}
        self.apply_all()

    def apply_all(self):
        for setting in SETTINGS:
            self._apply(setting)

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(self.values, file, indent=2)
        except OSError as error:
            print(f"Snowcat couldn't save its settings: {error}", flush=True)

    def _apply(self, setting):
        value = self.values[setting.key]
        if setting.to_module:
            value = setting.to_module(value)
        setattr(setting.module, setting.attr, value)

    def _load(self):
        """Read saved choices, ignoring anything missing, unknown or out of range."""
        try:
            with open(self.path, encoding="utf-8") as file:
                saved = json.load(file)
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        for setting in SETTINGS:
            value = saved.get(setting.key)
            if setting.is_switch and isinstance(value, bool):
                self.values[setting.key] = value
            elif not setting.is_switch and isinstance(value, (int, float)) and not isinstance(value, bool):
                self.values[setting.key] = min(setting.high, max(setting.low, value))
