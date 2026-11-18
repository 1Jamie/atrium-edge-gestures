"""
Action executors for triggering keyboard shortcuts, Steam chords, URLs, and commands.
"""

from __future__ import annotations

import errno
import logging
import os
import shlex
import socket
import subprocess
import time
from typing import List, Optional

import evdev
from evdev import UInput, ecodes

from .config import ActionConfig

logger = logging.getLogger("edge_gestures.actions")


def is_steam_running() -> bool:
    """Check if the Steam client process is running."""
    try:
        res = subprocess.run(["pgrep", "-x", "steam"], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


def is_game_mode() -> bool:
    """Check if currently running inside Gamescope / Gaming Mode."""
    xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gamescope" in xdg_desktop or "steamos" in xdg_desktop:
        return True
    try:
        res = subprocess.run(["pgrep", "-x", "gamescope"], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


def trigger_atrium_osk() -> bool:
    """
    Attempt to trigger Atrium's native on-screen keyboard via Unix domain socket.
    Uses a 50ms timeout to avoid blocking if the socket file is stale.
    """
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sock_path = os.path.join(xdg_runtime, "atrium-edge-gestures.sock")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.05)
        s.connect(sock_path)
        s.sendall(b"trigger\n")
        s.close()
        logger.info("Successfully triggered Atrium OSK via Unix domain socket.")
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        logger.debug(f"Atrium socket not available ({sock_path}): {e}")
        return False


def trigger_steam_pipe() -> bool:
    """
    Write steam://open/keyboard directly to ~/.steam/steam.pipe using O_NONBLOCK.
    Non-blocking write prevents hanging indefinitely if the pipe file exists but
    no reader process is attached.
    """
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".steam", "steam.pipe"),
        os.path.join(home, ".steam", "root", "steam.pipe"),
        os.path.join(home, ".local", "share", "Steam", "steam.pipe"),
    ]
    for pipe_path in candidates:
        if os.path.exists(pipe_path):
            try:
                fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                with os.fdopen(fd, "w") as f:
                    f.write("open steam://open/keyboard\n")
                    f.flush()
                logger.info(f"Triggered Steam virtual keyboard via non-blocking write to {pipe_path}")
                return True
            except OSError as e:
                # ENXIO (errno 6): No such device or address -> pipe exists on disk but Steam reader is dead
                logger.debug(f"Cannot write to steam pipe {pipe_path}: {e}")
                continue
    return False


def trigger_steam_url(url: str = "steam://open/keyboard") -> bool:
    """Trigger keyboard via Steam URL."""
    try:
        # First attempt non-blocking pipe for near-zero latency
        if url == "steam://open/keyboard" and trigger_steam_pipe():
            return True
        subprocess.Popen(
            ["steam", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(f"Triggered Steam URL: {url}")
        return True
    except Exception as e:
        logger.warning(f"Could not launch Steam URL '{url}': {e}")
        return False


def toggle_desktop_osk() -> bool:
    """
    Toggle native desktop on-screen keyboard (GNOME OSK or KDE virtual keyboard)
    via D-Bus as a fallback when Steam is not running.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    try:
        if "gnome" in desktop:
            res = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            is_active = "true" in res.stdout.lower()
            new_state = "false" if is_active else "true"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled", new_state],
                check=True,
                timeout=1.0,
            )
            logger.info(f"Toggled GNOME on-screen keyboard: {new_state}")
            return True
        elif "kde" in desktop:
            subprocess.run(
                [
                    "qdbus",
                    "org.kde.kwin",
                    "/KWin",
                    "org.kde.KWin.virtualKeyboardActive",
                ],
                capture_output=True,
                timeout=1.0,
            )
            logger.info("Toggled KDE virtual keyboard via D-Bus")
            return True
    except Exception as e:
        logger.warning(f"Could not toggle desktop OSK: {e}")
    return False


def resolve_keycode(name: str) -> Optional[int]:
    """Resolve an ecodes string like 'BTN_MODE' or 'KEY_LEFTMETA' to integer code."""
    if hasattr(ecodes, name):
        return getattr(ecodes, name)
    clean = name.strip().upper()
    if hasattr(ecodes, clean):
        return getattr(ecodes, clean)
    logger.warning(f"Unknown input code: '{name}'")
    return None


class SteamUrlTrigger:
    """Opens virtual keyboard or triggers actions using Steam URL protocol."""

    def __init__(self, url: str = "steam://open/keyboard"):
        self.url = url

    def trigger(self) -> bool:
        return trigger_steam_url(self.url)

    def close(self):
        pass


class GnomeOskTrigger:
    """Toggles the GNOME / KDE desktop on-screen keyboard."""

    def __init__(self):
        pass

    def trigger(self) -> bool:
        return toggle_desktop_osk()

    def close(self):
        pass


class AutoKeyboardTrigger:
    """
    Intelligent zero-device keyboard trigger:
    1. Checks for Atrium native Unix domain socket ($XDG_RUNTIME_DIR/atrium-edge-gestures.sock).
    2. If Steam is running: triggers steam.pipe (non-blocking) or steam://open/keyboard.
    3. If Steam is NOT running: falls back to native desktop OSK (GNOME / KDE via D-Bus).
    """

    def __init__(self, url: str = "steam://open/keyboard"):
        self.url = url

    def trigger(self) -> bool:
        # Priority 1: Inside Atrium
        if trigger_atrium_osk():
            return True

        # Priority 2: Steam running
        if is_steam_running():
            logger.info("Steam is running: triggering Steam On-Screen Keyboard...")
            if trigger_steam_pipe():
                return True
            return trigger_steam_url(self.url)

        # Priority 3: Desktop fallback
        logger.info("Steam is not running: falling back to desktop on-screen keyboard...")
        return toggle_desktop_osk()

    def close(self):
        pass


class CommandTrigger:
    """Executes a custom shell command."""

    def __init__(self, command: str):
        self.command = command

    def trigger(self) -> bool:
        if not self.command:
            return False
        try:
            logger.info(f"Executing command: {self.command}")
            subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to execute command '{self.command}': {e}")
            return False

    def close(self):
        pass


class SteamChordTrigger:
    """
    Legacy controller chord trigger (e.g. Guide + X).
    NOTE: Kept for explicit user opt-in, but deprecated by default
    to avoid primary seat conflicts in games like Black Ops 3.
    """

    def __init__(self, chord_buttons: Optional[List[str]] = None, press_duration: float = 0.06):
        if chord_buttons is None:
            chord_buttons = ["BTN_MODE", "BTN_X"]
        self.chord_names = chord_buttons
        self.press_duration = press_duration
        self.resolved_codes: List[int] = []
        for name in self.chord_names:
            code = resolve_keycode(name)
            if code is not None:
                self.resolved_codes.append(code)

        cap = {
            ecodes.EV_KEY: [
                ecodes.BTN_A,
                ecodes.BTN_B,
                ecodes.BTN_X,
                ecodes.BTN_Y,
                ecodes.BTN_MODE,
                ecodes.BTN_START,
                ecodes.BTN_SELECT,
                ecodes.BTN_TL,
                ecodes.BTN_TR,
            ],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, evdev.AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
            ],
        }

        try:
            self.uinput = UInput(
                cap,
                name="Edge Gestures Steam Controller",
                vendor=0x28DE,
                product=0x11FF,
                version=0x0110,
            )
            logger.info("Initialized persistent Steam Controller UInput.")
        except Exception as e:
            logger.error(f"Failed to create Steam Controller uinput: {e}")
            self.uinput = None

    def trigger(self) -> bool:
        if not self.uinput or not self.resolved_codes:
            return False
        try:
            logger.info(f"Firing Steam chord: {self.chord_names}")
            for code in self.resolved_codes:
                self.uinput.write(ecodes.EV_KEY, code, 1)
                self.uinput.syn()
                time.sleep(0.01)
            time.sleep(self.press_duration)
            for code in reversed(self.resolved_codes):
                self.uinput.write(ecodes.EV_KEY, code, 0)
                self.uinput.syn()
                time.sleep(0.01)
            return True
        except Exception as e:
            logger.error(f"Exception firing Steam chord: {e}")
            return False

    def close(self):
        if self.uinput:
            try:
                self.uinput.close()
            except Exception:
                pass
            self.uinput = None


class KeyboardChordTrigger:
    """
    Simulates a keyboard shortcut (e.g. Super + X or Ctrl + 1).
    """

    def __init__(self, key_names: Optional[List[str]] = None, press_duration: float = 0.05):
        if key_names is None:
            key_names = ["KEY_LEFTMETA", "KEY_X"]
        self.key_names = key_names
        self.press_duration = press_duration
        self.resolved_keys: List[int] = []
        for name in self.key_names:
            code = resolve_keycode(name)
            if code is not None:
                self.resolved_keys.append(code)

        cap = {
            ecodes.EV_KEY: self.resolved_keys
            + [
                ecodes.KEY_LEFTMETA,
                ecodes.KEY_LEFTCTRL,
                ecodes.KEY_LEFTSHIFT,
                ecodes.KEY_LEFTALT,
                ecodes.KEY_X,
                ecodes.KEY_1,
                ecodes.KEY_2,
            ]
        }

        try:
            self.uinput = UInput(cap, name="Edge Gestures Virtual Keyboard", version=0x3)
            logger.info("Initialized Virtual Keyboard for shortcut injection.")
        except Exception as e:
            logger.error(f"Failed to create virtual keyboard uinput: {e}")
            self.uinput = None

    def trigger(self) -> bool:
        if not self.uinput or not self.resolved_keys:
            return False
        try:
            logger.info(f"Firing keyboard chord: {self.key_names}")
            for code in self.resolved_keys:
                self.uinput.write(ecodes.EV_KEY, code, 1)
                self.uinput.syn()
                time.sleep(0.01)
            time.sleep(self.press_duration)
            for code in reversed(self.resolved_keys):
                self.uinput.write(ecodes.EV_KEY, code, 0)
                self.uinput.syn()
                time.sleep(0.01)
            return True
        except Exception as e:
            logger.error(f"Exception firing keyboard chord: {e}")
            return False

    def close(self):
        if self.uinput:
            try:
                self.uinput.close()
            except Exception:
                pass
            self.uinput = None


class ActionDispatcher:
    """Manages trigger instances corresponding to gesture action configs."""

    def __init__(self):
        self._triggers = []

    def create_trigger(self, config: ActionConfig):
        action_type = config.type.lower()
        if action_type in ("auto", "auto_keyboard", "steam_hybrid"):
            trigger = AutoKeyboardTrigger(url=config.url)
            self._triggers.append(trigger)
            return trigger
        elif action_type == "steam_url":
            trigger = SteamUrlTrigger(url=config.url)
            self._triggers.append(trigger)
            return trigger
        elif action_type == "desktop_osk":
            trigger = GnomeOskTrigger()
            self._triggers.append(trigger)
            return trigger
        elif action_type == "command":
            trigger = CommandTrigger(command=config.command)
            self._triggers.append(trigger)
            return trigger
        elif action_type == "steam_chord":
            trigger = SteamChordTrigger(
                chord_buttons=config.chord,
                press_duration=config.press_duration,
            )
            self._triggers.append(trigger)
            return trigger
        elif action_type == "keyboard_chord":
            trigger = KeyboardChordTrigger(
                key_names=config.keys,
                press_duration=config.press_duration,
            )
            self._triggers.append(trigger)
            return trigger
        else:
            logger.warning(f"Unknown action type '{config.type}', falling back to auto.")
            trigger = AutoKeyboardTrigger()
            self._triggers.append(trigger)
            return trigger

    def close(self):
        for trigger in self._triggers:
            trigger.close()
        self._triggers.clear()
