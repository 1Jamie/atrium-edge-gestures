"""
Multi-touch Type B event processor and edge gesture recognition engine.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import evdev
from evdev import ecodes

from .config import GestureConfig

logger = logging.getLogger("edge_gestures.detector")


@dataclass
class Hotzone:
    """Bounding box representing the trigger zone along an edge."""
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    def contains(self, x: int, y: int) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


def calculate_hotzone(
    gesture: GestureConfig,
    screen_width: int,
    screen_height: int,
) -> Hotzone:
    """
    Compute pixel bounding box for a gesture based on screen dimensions
    and edge configuration.
    """
    edge = gesture.edge.lower()
    depth = gesture.edge_depth_px
    start_ratio = max(0.0, min(1.0, gesture.span_start_ratio))
    end_ratio = max(0.0, min(1.0, gesture.span_end_ratio))
    if start_ratio > end_ratio:
        start_ratio, end_ratio = end_ratio, start_ratio

    if edge == "bottom":
        y_min = max(0, screen_height - depth)
        y_max = screen_height
        x_min = int(screen_width * start_ratio)
        x_max = int(screen_width * end_ratio)
    elif edge == "top":
        y_min = 0
        y_max = min(screen_height, depth)
        x_min = int(screen_width * start_ratio)
        x_max = int(screen_width * end_ratio)
    elif edge == "left":
        x_min = 0
        x_max = min(screen_width, depth)
        y_min = int(screen_height * start_ratio)
        y_max = int(screen_height * end_ratio)
    elif edge == "right":
        x_min = max(0, screen_width - depth)
        x_max = screen_width
        y_min = int(screen_height * start_ratio)
        y_max = int(screen_height * end_ratio)
    else:
        # Default to bottom
        y_min = max(0, screen_height - depth)
        y_max = screen_height
        x_min = int(screen_width * start_ratio)
        x_max = int(screen_width * end_ratio)

    return Hotzone(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)


@dataclass
class RecognizedGesture:
    config: GestureConfig
    hotzone: Hotzone
    action_trigger_fn: Callable[[], bool]


@dataclass
class TouchSlot:
    """State tracking for a single multi-touch slot."""
    slot_id: int
    tracking_id: int = -1
    is_active: bool = False
    x: int = 0
    y: int = 0
    start_x: int = 0
    start_y: int = 0
    start_time: float = 0.0
    needs_init: bool = False
    # Set of gestures this touch started within
    candidate_gestures: Set[str] = field(default_factory=set)


class GestureDetector:
    """
    Parses raw Linux evdev multi-touch Type B events and detects directional edge swipes.
    """

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        gestures: List[Tuple[GestureConfig, Callable[[], bool]]],
        debounce_seconds: float = 0.6,
        on_touch_debug: Optional[Callable[[str], None]] = None,
    ):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.debounce_seconds = debounce_seconds
        self.on_touch_debug = on_touch_debug

        self.last_trigger_time: float = 0.0

        # Build recognized gestures with computed hotzones
        self.gestures: Dict[str, RecognizedGesture] = {}
        for g_cfg, trigger_fn in gestures:
            if not g_cfg.enabled:
                continue
            hz = calculate_hotzone(g_cfg, screen_width, screen_height)
            logger.info(
                f"Configured gesture '{g_cfg.name}' on {g_cfg.edge} edge: "
                f"hotzone=[X: {hz.x_min}..{hz.x_max}, Y: {hz.y_min}..{hz.y_max}], "
                f"direction={g_cfg.direction}, threshold={g_cfg.swipe_threshold_px}px"
            )
            self.gestures[g_cfg.name] = RecognizedGesture(
                config=g_cfg,
                hotzone=hz,
                action_trigger_fn=trigger_fn,
            )

        # Multi-touch slot state (up to 10 slots supported by kernel)
        self.slots: Dict[int, TouchSlot] = {i: TouchSlot(slot_id=i) for i in range(16)}
        self.current_slot: int = 0

    def process_event(self, event: evdev.InputEvent) -> Optional[str]:
        """
        Feed an evdev event. Returns the name of the triggered gesture if a gesture matched.
        """
        # Handle multi-touch slot selection
        if event.type == ecodes.EV_ABS:
            slot = self.slots.get(self.current_slot)
            if not slot:
                return None

            if event.code == ecodes.ABS_MT_SLOT:
                self.current_slot = event.value
                return None

            elif event.code == ecodes.ABS_MT_TRACKING_ID:
                tracking_id = event.value
                if tracking_id >= 0:
                    # New touch down or tracking update
                    slot.tracking_id = tracking_id
                    slot.is_active = True
                    slot.start_time = time.monotonic()
                    slot.needs_init = True
                    slot.candidate_gestures.clear()
                    if self.on_touch_debug:
                        self.on_touch_debug(f"Touch DOWN (Slot {slot.slot_id}, ID {tracking_id})")
                else:
                    # Touch contact released (-1)
                    if self.on_touch_debug and slot.is_active:
                        self.on_touch_debug(f"Touch UP (Slot {slot.slot_id}, ID {slot.tracking_id})")
                    slot.is_active = False
                    slot.tracking_id = -1
                    slot.candidate_gestures.clear()
                    slot.needs_init = False
                return None

            elif event.code == ecodes.ABS_MT_POSITION_X:
                slot.x = event.value
                return None

            elif event.code == ecodes.ABS_MT_POSITION_Y:
                slot.y = event.value
                return None

            # Legacy single-touch fallback
            elif event.code == ecodes.ABS_X:
                slot.x = event.value
                return None
            elif event.code == ecodes.ABS_Y:
                slot.y = event.value
                return None

        elif event.type == ecodes.EV_KEY:
            if event.code == ecodes.BTN_TOUCH:
                slot = self.slots.get(self.current_slot)
                if slot and event.value == 1 and not slot.is_active:
                    slot.is_active = True
                    slot.tracking_id = 1
                    slot.start_time = time.monotonic()
                    slot.needs_init = True
                elif slot and event.value == 0:
                    slot.is_active = False
                    slot.tracking_id = -1
                    slot.candidate_gestures.clear()
                    slot.needs_init = False
                return None

        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            # End of an atomic multi-touch frame: Evaluate gesture states
            return self._evaluate_frame()

        return None

    def _evaluate_frame(self) -> Optional[str]:
        now = time.monotonic()
        triggered_gesture_name: Optional[str] = None

        for slot_idx, slot in self.slots.items():
            if not slot.is_active or slot.tracking_id < 0:
                continue

            # Initialize starting position on the first report frame with valid coordinates
            if slot.needs_init:
                slot.start_x = slot.x
                slot.start_y = slot.y
                slot.needs_init = False
                slot.candidate_gestures.clear()

                # Find any gestures whose hotzone encompasses the initial touch
                for name, g in self.gestures.items():
                    if g.hotzone.contains(slot.start_x, slot.start_y):
                        slot.candidate_gestures.add(name)
                        if self.on_touch_debug:
                            self.on_touch_debug(
                                f"Hotzone ENTER [{name}]: X={slot.start_x}, Y={slot.start_y}"
                            )

            if not slot.candidate_gestures:
                continue

            # Check candidates
            dx = slot.x - slot.start_x
            dy = slot.y - slot.start_y
            elapsed = now - slot.start_time

            for g_name in list(slot.candidate_gestures):
                g = self.gestures.get(g_name)
                if not g:
                    slot.candidate_gestures.remove(g_name)
                    continue

                cfg = g.config

                # Check duration expiration
                if elapsed > cfg.max_duration:
                    slot.candidate_gestures.remove(g_name)
                    continue

                # Check direction criteria
                swipe_matched = False
                if cfg.direction == "up":
                    # Dragging upward: Y decreases (dy negative)
                    travel = -dy
                    perp_deviation = abs(dx)
                    if travel >= cfg.swipe_threshold_px and perp_deviation <= cfg.max_deviation_px:
                        swipe_matched = True
                elif cfg.direction == "down":
                    # Dragging downward: Y increases (dy positive)
                    travel = dy
                    perp_deviation = abs(dx)
                    if travel >= cfg.swipe_threshold_px and perp_deviation <= cfg.max_deviation_px:
                        swipe_matched = True
                elif cfg.direction == "left":
                    # Dragging leftward: X decreases (dx negative)
                    travel = -dx
                    perp_deviation = abs(dy)
                    if travel >= cfg.swipe_threshold_px and perp_deviation <= cfg.max_deviation_px:
                        swipe_matched = True
                elif cfg.direction == "right":
                    # Dragging rightward: X increases (dx positive)
                    travel = dx
                    perp_deviation = abs(dy)
                    if travel >= cfg.swipe_threshold_px and perp_deviation <= cfg.max_deviation_px:
                        swipe_matched = True

                if swipe_matched:
                    # Remove from candidates so this stroke doesn't re-trigger
                    slot.candidate_gestures.remove(g_name)

                    # Check global debounce
                    if (now - self.last_trigger_time) < self.debounce_seconds:
                        logger.debug(f"Gesture '{g_name}' matched but suppressed by debounce.")
                        continue

                    self.last_trigger_time = now
                    logger.info(
                        f"Gesture DETECTED: '{g_name}' (travel={travel}px, "
                        f"elapsed={elapsed*1000:.1f}ms, dev={perp_deviation}px)"
                    )
                    if self.on_touch_debug:
                        self.on_touch_debug(
                            f"TRIGGERED: {g_name} (travel={travel}px, dt={elapsed*1000:.0f}ms)"
                        )

                    # Fire action trigger
                    try:
                        g.action_trigger_fn()
                    except Exception as e:
                        logger.error(f"Error executing action for '{g_name}': {e}")

                    triggered_gesture_name = g_name
                    break

        return triggered_gesture_name
