"""
Configuration loading and validation for Edge Gestures.
"""

from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger("edge_gestures.config")

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "edge-gestures" / "config.yaml"


@dataclass
class ActionConfig:
    type: str = "auto"  # "auto", "steam_url", "desktop_osk", "command", "steam_chord", "keyboard_chord"
    # For steam_chord:
    chord: List[str] = field(default_factory=lambda: ["BTN_MODE", "BTN_X"])
    # For keyboard_chord:
    keys: List[str] = field(default_factory=lambda: ["KEY_LEFTMETA", "KEY_X"])
    # For steam_url:
    url: str = "steam://open/keyboard"
    # For command:
    command: str = ""
    # Hold duration for chord press
    press_duration: float = 0.06


@dataclass
class GestureConfig:
    name: str = "bottom_swipe_up"
    enabled: bool = True
    edge: str = "bottom"  # "bottom", "top", "left", "right"
    direction: str = "up"  # "up", "down", "left", "right"
    edge_depth_px: int = 45  # Pixel depth from the edge boundary
    span_start_ratio: float = 0.20  # Percentage along the edge (0.0 to 1.0)
    span_end_ratio: float = 0.80  # Percentage along the edge (0.0 to 1.0)
    swipe_threshold_px: int = 35  # Min distance travelled in swipe direction
    max_deviation_px: int = 100  # Max allowable drift perpendicular to swipe
    max_duration: float = 0.35  # Max duration of swipe in seconds
    action: ActionConfig = field(default_factory=ActionConfig)


@dataclass
class DeviceConfig:
    path: str = "auto"
    name: str = ""
    phys: str = ""
    name_filters: List[str] = field(
        default_factory=lambda: [
            "touch",
            "goodix",
            "nvtk",
            "elan",
            "fts",
            "ilitek",
            "focaltech",
            "atmel",
        ]
    )


@dataclass
class AppConfig:
    gui_backend: str = "lotus"  # "lotus" (Servo 0.7.0) or "gtk" (Libadwaita)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    debounce_seconds: float = 0.6  # Min delay between triggering any gesture
    gestures: List[GestureConfig] = field(default_factory=list)


DEFAULT_YAML_TEMPLATE = """# Edge Gestures Configuration
# Location: ~/.config/edge-gestures/config.yaml

# Configurator GUI engine: "lotus" (Servo 0.7.0 + Node) or "gtk" (Libadwaita)
gui_backend: "lotus"

device:
  # Path to touchscreen event device node, e.g. /dev/input/event5
  # Set to "auto" to detect the touchscreen automatically
  path: "auto"
  # Substrings checked when auto-detecting touchscreen device name
  name_filters:
    - "touch"
    - "goodix"
    - "nvtk"       # ROG Ally / Ally X Novatek touchscreen
    - "elan"
    - "fts"
    - "ilitek"

# Global cooldown between firing gestures (seconds)
debounce_seconds: 0.6

gestures:
  # Bottom edge swipe-up: Open Steam On-Screen Keyboard
  - name: "bottom_open_keyboard"
    enabled: true
    edge: "bottom"            # Options: bottom, top, left, right
    direction: "up"           # Options: up, down, left, right
    edge_depth_px: 45         # Hotzone thickness inward from screen bottom
    span_start_ratio: 0.20    # Start hotzone at 20% width (avoid lower-left corner)
    span_end_ratio: 0.80      # End hotzone at 80% width (avoid lower-right corner)
    swipe_threshold_px: 35    # Pixels finger must move upward
    max_deviation_px: 90      # Maximum horizontal drift allowed during swipe
    max_duration: 0.35        # Gesture must complete within 350ms
    action:
      # Options:
      #  - "auto":        Smart trigger! Uses Steam keyboard if Steam is running; falls back to Desktop OSK if Steam is stopped
      #  - "steam_chord": Emulates controller Guide + X (Steam + X) chord via virtual gamepad
      #  - "steam_url":   Executes `steam steam://open/keyboard`
      #  - "desktop_osk": Toggles native desktop on-screen keyboard (GNOME/KDE)
      #  - "keyboard_chord": Emulates physical keyboard combo (e.g. Super+X)
      #  - "command":     Executes a custom shell command
      type: "auto"
      chord: ["BTN_MODE", "BTN_X"]
      # url: "steam://open/keyboard"
      # keys: ["KEY_LEFTMETA", "KEY_X"]
      # command: "notify-send 'Gesture Detected'"

  # Optional example: Top edge swipe-down for Steam Quick Access / Menu
  # - name: "top_swipe_down"
  #   enabled: false
  #   edge: "top"
  #   direction: "down"
  #   edge_depth_px: 40
  #   span_start_ratio: 0.25
  #   span_end_ratio: 0.75
  #   swipe_threshold_px: 40
  #   max_deviation_px: 90
  #   max_duration: 0.35
  #   action:
  #     type: "steam_url"
  #     url: "steam://open/keyboard"
"""


def parse_action_config(data: Dict[str, Any]) -> ActionConfig:
    action_type = data.get("type", "steam_chord")
    chord = data.get("chord", ["BTN_MODE", "BTN_X"])
    keys = data.get("keys", ["KEY_LEFTMETA", "KEY_X"])
    url = data.get("url", "steam://open/keyboard")
    command = data.get("command", "")
    press_duration = float(data.get("press_duration", 0.06))
    return ActionConfig(
        type=action_type,
        chord=chord,
        keys=keys,
        url=url,
        command=command,
        press_duration=press_duration,
    )


def parse_gesture_config(data: Dict[str, Any]) -> GestureConfig:
    name = data.get("name", "unnamed_gesture")
    enabled = data.get("enabled", True)
    edge = data.get("edge", "bottom").lower()
    direction = data.get("direction", "up").lower()
    edge_depth_px = int(data.get("edge_depth_px", 45))
    span_start_ratio = float(data.get("span_start_ratio", 0.20))
    span_end_ratio = float(data.get("span_end_ratio", 0.80))
    swipe_threshold_px = int(data.get("swipe_threshold_px", 35))
    max_deviation_px = int(data.get("max_deviation_px", 100))
    max_duration = float(data.get("max_duration", 0.35))

    action_data = data.get("action", {})
    action = parse_action_config(action_data)

    return GestureConfig(
        name=name,
        enabled=enabled,
        edge=edge,
        direction=direction,
        edge_depth_px=edge_depth_px,
        span_start_ratio=span_start_ratio,
        span_end_ratio=span_end_ratio,
        swipe_threshold_px=swipe_threshold_px,
        max_deviation_px=max_deviation_px,
        max_duration=max_duration,
        action=action,
    )


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.info(f"Config file not found at {config_path}. Creating default config.")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(DEFAULT_YAML_TEMPLATE)

    try:
        content = config_path.read_text()
        if yaml:
            data = yaml.safe_load(content) or {}
        else:
            logger.warning("PyYAML not found, using default configuration.")
            data = {}
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {e}. Using defaults.")
        data = {}

    device_data = data.get("device", {})
    dev_config = DeviceConfig(
        path=device_data.get("path", "auto"),
        name_filters=device_data.get(
            "name_filters",
            ["touch", "goodix", "nvtk", "elan", "fts", "ilitek"],
        ),
    )

    debounce = float(data.get("debounce_seconds", 0.6))

    gestures_data = data.get("gestures", [])
    gestures: List[GestureConfig] = []
    if gestures_data:
        for g in gestures_data:
            gestures.append(parse_gesture_config(g))
    else:
        # Default gesture
        gestures.append(GestureConfig())

    gui_backend = str(data.get("gui_backend", "lotus")).lower()
    if gui_backend not in ("lotus", "gtk"):
        gui_backend = "lotus"

    return AppConfig(
        gui_backend=gui_backend,
        device=dev_config,
        debounce_seconds=debounce,
        gestures=gestures,
    )


def save_config(config: AppConfig, config_path: Optional[Path] = None) -> Path:
    """Save an AppConfig instance back to YAML file."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot save configuration.")

    export_dict = {
        "gui_backend": config.gui_backend,
        "device": {
            "path": config.device.path,
            "name_filters": config.device.name_filters,
        },
        "debounce_seconds": config.debounce_seconds,
        "gestures": [
            {
                "name": g.name,
                "enabled": g.enabled,
                "edge": g.edge,
                "direction": g.direction,
                "edge_depth_px": g.edge_depth_px,
                "span_start_ratio": g.span_start_ratio,
                "span_end_ratio": g.span_end_ratio,
                "swipe_threshold_px": g.swipe_threshold_px,
                "max_deviation_px": g.max_deviation_px,
                "max_duration": g.max_duration,
                "action": {
                    "type": g.action.type,
                    "chord": g.action.chord,
                    "keys": g.action.keys,
                    "url": g.action.url,
                    "command": g.action.command,
                    "press_duration": g.action.press_duration,
                },
            }
            for g in config.gestures
        ],
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(export_dict, sort_keys=False))
    return config_path
