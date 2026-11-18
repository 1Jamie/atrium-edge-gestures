"""
Input device discovery, validation, and auto-reconnection.
"""

from __future__ import annotations

import glob
import logging
import os
import time
from typing import List, Optional, Tuple

import evdev
from evdev import InputDevice, ecodes

from .config import DeviceConfig

logger = logging.getLogger("edge_gestures.device")


def is_touchscreen(dev: InputDevice, name_filters: Optional[List[str]] = None) -> bool:
    """
    Check if an input device is a multi-touch touchscreen.
    Verifies multi-touch axes and touch button capabilities.
    """
    try:
        caps = dev.capabilities()
    except Exception:
        return False

    # Check for EV_ABS (Absolute axes)
    if ecodes.EV_ABS not in caps:
        return False

    abs_caps = dict(caps[ecodes.EV_ABS])
    has_mt_x = ecodes.ABS_MT_POSITION_X in abs_caps
    has_mt_y = ecodes.ABS_MT_POSITION_Y in abs_caps
    has_legacy_x = ecodes.ABS_X in abs_caps
    has_legacy_y = ecodes.ABS_Y in abs_caps

    # Must support either multi-touch or legacy absolute coordinates
    if not ((has_mt_x and has_mt_y) or (has_legacy_x and has_legacy_y)):
        return False

    # Check for touch key/button if available
    key_caps = caps.get(ecodes.EV_KEY, [])
    is_touch_key = ecodes.BTN_TOUCH in key_caps

    # Also check device name if filters are specified
    dev_name = dev.name.lower()
    matches_filter = False
    if name_filters:
        for f in name_filters:
            if f.lower() in dev_name:
                matches_filter = True
                break

    # If it has BTN_TOUCH and MT coords, it's almost certainly a touchscreen
    if (has_mt_x and has_mt_y) and (is_touch_key or matches_filter):
        return True

    # Fallback: matches name filter and has MT axes
    if matches_filter and (has_mt_x and has_mt_y):
        return True

    return False


def list_touch_devices() -> List[Tuple[InputDevice, bool]]:
    """List all available input devices and flag which ones are touchscreens."""
    devices = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice(path)
            touch = is_touchscreen(dev)
            devices.append((dev, touch))
        except (PermissionError, OSError):
            continue
    return devices


def get_by_path_symlink(event_path: str) -> Optional[str]:
    """Find stable /dev/input/by-path/... symlink pointing to an event device."""
    target_basename = os.path.basename(event_path)
    for p in glob.glob("/dev/input/by-path/*"):
        try:
            if os.path.basename(os.path.realpath(p)) == target_basename:
                return p
        except Exception:
            continue
    return None


def find_touchscreen(config: DeviceConfig) -> Optional[InputDevice]:
    """
    Find the touchscreen device based on configuration.
    Supports:
    1. Stable /dev/input/by-path/ symlink or explicit path.
    2. Stable hardware matching via name + phys.
    3. Automatic detection with manufacturer priority (Novatek, Goodix, Elan, etc.).
    """
    # 1. Try configured path (resolves by-path symlink or explicit node)
    if config.path and config.path.lower() != "auto":
        if os.path.exists(config.path):
            try:
                dev = InputDevice(config.path)
                logger.info(f"Using explicitly specified device: {dev.name} at {dev.path}")
                return dev
            except Exception as e:
                logger.error(f"Failed to open explicit device {config.path}: {e}")
        else:
            logger.warning(f"Explicit device path '{config.path}' not found on disk.")

    # 2. Try matching by hardware signature (name + phys) if configured
    if config.name or config.phys:
        for p in sorted(glob.glob("/dev/input/event*")):
            try:
                dev = InputDevice(p)
                name_match = not config.name or dev.name == config.name
                phys_match = not config.phys or (dev.phys or "") == config.phys
                if name_match and phys_match:
                    logger.info(f"Matched touchscreen by hardware signature: {dev.name} ({dev.path})")
                    return dev
            except (PermissionError, OSError):
                continue

    # 3. Auto-detection
    touch_candidates: List[InputDevice] = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice(path)
            if is_touchscreen(dev, config.name_filters):
                touch_candidates.append(dev)
        except (PermissionError, OSError):
            continue

    if not touch_candidates:
        return None

    # Prefer devices matching specific known handheld controllers
    for dev in touch_candidates:
        name_lower = dev.name.lower()
        if any(brand in name_lower for brand in ["nvtk", "goodix", "elan", "fts", "touchscreen"]):
            logger.info(f"Auto-selected touchscreen: {dev.name} ({dev.path})")
            return dev

    selected = touch_candidates[0]
    logger.info(f"Auto-selected touchscreen: {selected.name} ({selected.path})")
    return selected


def get_screen_bounds(dev: InputDevice) -> Tuple[int, int]:
    """
    Get screen width and height from device AbsInfo.
    Falls back to 1920x1080 if AbsInfo is missing.
    """
    width = 1920
    height = 1080
    try:
        abs_x = dev.absinfo(ecodes.ABS_MT_POSITION_X)
        if abs_x and abs_x.max > 0:
            width = abs_x.max
    except Exception:
        pass

    try:
        abs_y = dev.absinfo(ecodes.ABS_MT_POSITION_Y)
        if abs_y and abs_y.max > 0:
            height = abs_y.max
    except Exception:
        pass

    return width, height
