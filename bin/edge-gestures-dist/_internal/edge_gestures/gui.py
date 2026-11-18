#!/usr/bin/env python3
"""
GTK4 / Libadwaita Graphical Configuration Application for Edge Gestures.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import gi

try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, Gtk
except (ValueError, ImportError) as e:
    print(f"[ERROR] Failed to load GTK4 / Libadwaita: {e}", file=sys.stderr)
    print("Please install python3-gobject, gtk4, and libadwaita.", file=sys.stderr)
    sys.exit(1)

try:
    from .config import (
        DEFAULT_CONFIG_PATH,
        AppConfig,
        GestureConfig,
        load_config,
        save_config,
    )
except ImportError:
    from edge_gestures.config import (
        DEFAULT_CONFIG_PATH,
        AppConfig,
        GestureConfig,
        load_config,
        save_config,
    )


@dataclass
class GestureWidgets:
    """Holds references to UI controls for a specific gesture."""

    gesture: GestureConfig
    enabled_row: Adw.SwitchRow
    edge_row: Adw.ComboRow
    direction_row: Adw.ComboRow
    depth_row: Adw.SpinRow
    threshold_row: Adw.SpinRow
    duration_row: Adw.SpinRow
    action_row: Adw.ComboRow
    action_model: Gtk.StringList
    action_types: List[str]
    edge_types: List[str]
    dir_types: List[str]

    def apply_to_model(self) -> None:
        self.gesture.enabled = self.enabled_row.get_active()
        self.gesture.edge = self.edge_types[self.edge_row.get_selected()]
        self.gesture.direction = self.dir_types[self.direction_row.get_selected()]
        self.gesture.edge_depth_px = int(self.depth_row.get_value())
        self.gesture.swipe_threshold_px = int(self.threshold_row.get_value())
        self.gesture.max_duration = round(self.duration_row.get_value(), 2)
        self.gesture.action.type = self.action_types[self.action_row.get_selected()]


class ConfigWindow(Adw.ApplicationWindow):
    def __init__(self, config_path: Optional[Path] = None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Edge Gestures Configuration")
        self.set_default_size(540, 720)

        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.cfg: AppConfig = load_config(self.config_path)
        self.gesture_widget_list: List[GestureWidgets] = []

        # Setup Toast Overlay as root window content
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Header bar
        header = Adw.HeaderBar()
        save_btn = Gtk.Button(label="Save & Apply")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save_clicked)
        header.pack_end(save_btn)

        # Main Layout
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        self.toast_overlay.set_child(toolbar_view)

        page = Adw.PreferencesPage()
        toolbar_view.set_content(page)

        # --- General Settings Group ---
        general_group = Adw.PreferencesGroup(title="General")
        page.add(general_group)

        # Configurator GUI Backend Switch
        self.backend_options = ["lotus", "gtk"]
        backend_labels = ["Lotus-GUI (Servo 0.7.0 + Node)", "GTK4 / Libadwaita (Python)"]
        backend_model = Gtk.StringList.new(backend_labels)
        self.backend_row = Adw.ComboRow(
            title="Configurator Engine",
            subtitle="Default GUI engine launched next time",
            model=backend_model,
        )
        curr_backend = getattr(self.cfg, "gui_backend", "lotus").lower()
        backend_idx = self.backend_options.index(curr_backend) if curr_backend in self.backend_options else 1
        self.backend_row.set_selected(backend_idx)
        general_group.add(self.backend_row)

        # Touchscreen Device Path
        self.device_path_row = Adw.EntryRow()
        self.device_path_row.set_title("Touchscreen Device")
        self.device_path_row.set_text(self.cfg.device.path or "auto")
        general_group.add(self.device_path_row)

        # Debounce Cooldown
        self.debounce_row = Adw.SpinRow.new_with_range(0.1, 3.0, 0.1)
        self.debounce_row.set_title("Cooldown (Debounce)")
        self.debounce_row.set_subtitle("Minimum seconds between gestures to prevent duplicate triggers")
        self.debounce_row.set_value(self.cfg.debounce_seconds)
        general_group.add(self.debounce_row)

        # --- Gestures Settings Group ---
        edge_options = ["bottom", "top", "left", "right"]
        dir_options = ["up", "down", "left", "right"]
        action_options = ["auto", "steam_chord", "steam_url", "desktop_osk", "keyboard_chord", "command"]

        for gesture in self.cfg.gestures:
            gest_group = Adw.PreferencesGroup(
                title=f"Gesture: {gesture.name}",
                description=f"Configure trigger boundaries and actions",
            )
            page.add(gest_group)

            # Enabled Switch
            enabled_row = Adw.SwitchRow()
            enabled_row.set_title("Enable Gesture")
            enabled_row.set_active(gesture.enabled)
            gest_group.add(enabled_row)

            # Edge Selector
            edge_model = Gtk.StringList.new(edge_options)
            edge_row = Adw.ComboRow(
                title="Screen Edge",
                subtitle="Boundary of the screen where touch begins",
                model=edge_model,
            )
            edge_idx = edge_options.index(gesture.edge) if gesture.edge in edge_options else 0
            edge_row.set_selected(edge_idx)
            gest_group.add(edge_row)

            # Direction Selector
            dir_model = Gtk.StringList.new(dir_options)
            dir_row = Adw.ComboRow(
                title="Swipe Direction",
                subtitle="Direction finger moves inward from the edge",
                model=dir_model,
            )
            dir_idx = dir_options.index(gesture.direction) if gesture.direction in dir_options else 0
            dir_row.set_selected(dir_idx)
            gest_group.add(dir_row)

            # Edge Depth
            depth_row = Adw.SpinRow.new_with_range(15, 120, 5)
            depth_row.set_title("Edge Depth")
            depth_row.set_subtitle("Hotzone thickness inward from screen boundary (px)")
            depth_row.set_value(gesture.edge_depth_px)
            gest_group.add(depth_row)

            # Swipe Threshold
            threshold_row = Adw.SpinRow.new_with_range(15, 200, 5)
            threshold_row.set_title("Swipe Travel Threshold")
            threshold_row.set_subtitle("Distance finger must move before triggering (px)")
            threshold_row.set_value(gesture.swipe_threshold_px)
            gest_group.add(threshold_row)

            # Max Duration
            duration_row = Adw.SpinRow.new_with_range(0.1, 1.0, 0.05)
            duration_row.set_title("Maximum Swipe Duration")
            duration_row.set_subtitle("Time window allowed to complete swipe (seconds)")
            duration_row.set_value(gesture.max_duration)
            gest_group.add(duration_row)

            # Action Selector
            action_model = Gtk.StringList.new(action_options)
            action_row = Adw.ComboRow(
                title="Action Backend",
                subtitle="Method used to invoke keyboard or shortcut",
                model=action_model,
            )
            curr_action = gesture.action.type.lower()
            act_idx = action_options.index(curr_action) if curr_action in action_options else 0
            action_row.set_selected(act_idx)
            gest_group.add(action_row)

            self.gesture_widget_list.append(
                GestureWidgets(
                    gesture=gesture,
                    enabled_row=enabled_row,
                    edge_row=edge_row,
                    direction_row=dir_row,
                    depth_row=depth_row,
                    threshold_row=threshold_row,
                    duration_row=duration_row,
                    action_row=action_row,
                    action_model=action_model,
                    action_types=action_options,
                    edge_types=edge_options,
                    dir_types=dir_options,
                )
            )

    def on_save_clicked(self, _btn):
        # Update general settings
        self.cfg.gui_backend = self.backend_options[self.backend_row.get_selected()]
        self.cfg.debounce_seconds = round(self.debounce_row.get_value(), 2)
        dev_path = self.device_path_row.get_text().strip()
        self.cfg.device.path = dev_path if dev_path else "auto"

        # Update each gesture from its UI controls
        for gw in self.gesture_widget_list:
            gw.apply_to_model()

        # Save to YAML
        try:
            save_config(self.cfg, self.config_path)
        except Exception as e:
            self.show_toast(f"Error saving config: {e}")
            return

        # Attempt to restart service if active
        res = subprocess.run(
            ["systemctl", "--user", "try-restart", "edge-gestures.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            self.show_toast("Configuration saved & service restarted!")
        else:
            self.show_toast("Configuration saved!")

    def show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        toast.set_use_markup(False)
        self.toast_overlay.add_toast(toast)
        print(f"[UI] {text}")


class ConfigApp(Adw.Application):
    def __init__(self, config_path: Optional[Path] = None):
        super().__init__(
            application_id="io.github.edge_gestures.config",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.config_path = config_path

    def do_activate(self):
        win = ConfigWindow(config_path=self.config_path, application=self)
        win.present()


def main(config_path: Optional[Path] = None, args: Optional[List[str]] = None) -> int:
    app = ConfigApp(config_path=config_path)
    cli_args = [sys.argv[0]] if args is None else [sys.argv[0]] + args
    return app.run(cli_args)


if __name__ == "__main__":
    sys.exit(main())
