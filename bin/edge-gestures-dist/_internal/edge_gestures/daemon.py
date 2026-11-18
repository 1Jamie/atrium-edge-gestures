"""
Edge Gestures Daemon loop with auto-reconnection, SIGHUP dynamic reload, and signal management.
"""

from __future__ import annotations

import logging
import os
import select
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from .actions import ActionDispatcher
from .config import AppConfig, load_config
from .detector import GestureDetector
from .device import find_touchscreen, get_screen_bounds

logger = logging.getLogger("edge_gestures.daemon")


class EdgeGesturesDaemon:
    """Daemon running edge gesture detection loop with live SIGHUP reloading."""

    def __init__(self, config: Optional[AppConfig] = None, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.config = config or load_config(config_path)
        self.running = False
        self._reload_requested = False
        self.dispatcher = ActionDispatcher()

    def stop(self, *args):
        logger.info("Stopping Edge Gestures daemon...")
        self.running = False

    def on_sighup(self, *args):
        logger.info("SIGHUP received: scheduling configuration reload...")
        self._reload_requested = True

    def run(self, debug: bool = False):
        self.running = True

        # Register signal handlers
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self.on_sighup)

        logger.info("Starting Edge Gestures Daemon...")

        while self.running:
            dev = find_touchscreen(self.config.device)
            if not dev:
                logger.warning("No touchscreen found. Retrying in 2 seconds...")
                # Sleep in short chunks so signals can interrupt promptly
                for _ in range(20):
                    if not self.running:
                        break
                    time.sleep(0.1)
                continue

            width, height = get_screen_bounds(dev)
            logger.info(f"Connected to '{dev.name}' ({dev.path}) - Resolution: {width}x{height}")

            # Prepare gestures and action triggers
            def build_detector():
                self.dispatcher.close()
                configured_gestures = []
                for g_cfg in self.config.gestures:
                    if not g_cfg.enabled:
                        continue
                    trigger_obj = self.dispatcher.create_trigger(g_cfg.action)
                    configured_gestures.append((g_cfg, trigger_obj.trigger))

                return GestureDetector(
                    screen_width=width,
                    screen_height=height,
                    gestures=configured_gestures,
                    debounce_seconds=self.config.debounce_seconds,
                )

            detector = build_detector()

            # Event reading loop with select() so signals interrupt promptly
            logger.info("Listening for edge gestures...")
            device_switch_needed = False
            try:
                while self.running and not device_switch_needed:
                    # Timeout of 0.5s allows checking flags regularly
                    try:
                        r, _, _ = select.select([dev.fd], [], [], 0.5)
                    except (InterruptedError, ValueError):
                        r = []

                    # Check if live config reload was requested via SIGHUP
                    if self._reload_requested:
                        self._reload_requested = False
                        try:
                            new_cfg = load_config(self.config_path)
                            old_dev_cfg = self.config.device
                            new_dev_cfg = new_cfg.device
                            self.config = new_cfg

                            # If touchscreen device settings changed, switch devices
                            if (
                                old_dev_cfg.path != new_dev_cfg.path
                                or old_dev_cfg.name != new_dev_cfg.name
                                or old_dev_cfg.phys != new_dev_cfg.phys
                            ):
                                logger.info("Touchscreen device configuration changed. Switching input device...")
                                device_switch_needed = True
                                break
                            else:
                                # Rebuild detector with new gestures / debounce thresholds without dropping device
                                detector = build_detector()
                                logger.info("Dynamic SIGHUP configuration reload applied cleanly (zero restart).")
                        except Exception as reload_err:
                            logger.error(f"Failed to reload config on SIGHUP: {reload_err}", exc_info=True)

                    if not r:
                        continue

                    for event in dev.read():
                        detector.process_event(event)

            except (OSError, IOError) as e:
                if self.running and not device_switch_needed:
                    logger.warning(f"Device disconnected or read error: {e}. Attempting reconnect...")
                    time.sleep(1.5)
            except Exception as e:
                logger.error(f"Unexpected error in event loop: {e}", exc_info=True)
                time.sleep(1.0)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass

        # Cleanup
        self.dispatcher.close()
        logger.info("Edge Gestures Daemon terminated cleanly.")
