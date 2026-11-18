"""
Command Line Interface for Edge Gestures daemon and diagnostics.
"""

from __future__ import annotations

import argparse
import logging
import os
import select
import subprocess
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config

SYSTEMD_SERVICE_NAME = "edge-gestures.service"
USER_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
DESKTOP_ENTRY_NAME = "edge-gestures-config.desktop"
USER_APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_run(args):
    from .daemon import EdgeGesturesDaemon

    setup_logging(args.verbose)
    config_path = Path(args.config) if args.config else None
    daemon = EdgeGesturesDaemon(config_path=config_path)
    daemon.run(debug=args.verbose)


def cmd_test(args):
    """Interactive visual touch & gesture test monitor."""
    from .actions import ActionDispatcher
    from .detector import GestureDetector, calculate_hotzone
    from .device import find_touchscreen, get_screen_bounds

    setup_logging(True)
    config_path = Path(args.config) if args.config else None
    cfg = load_config(config_path)

    dev = find_touchscreen(cfg.device)
    if not dev:
        print("\n[ERROR] No touchscreen device found.")
        print("Run 'edge-gestures devices' to view all connected input devices.\n")
        sys.exit(1)

    width, height = get_screen_bounds(dev)
    print("=" * 65)
    print(f" TOUCH GESTURE TEST MONITOR")
    print(f" Device    : {dev.name} ({dev.path})")
    print(f" Resolution: {width} x {height}")
    print("=" * 65)

    print("\nConfigured Gestures & Hotzones:")
    for g in cfg.gestures:
        if not g.enabled:
            continue
        hz = calculate_hotzone(g, width, height)
        print(
            f"  - [{g.name}] Edge: {g.edge} ({g.direction.upper()}) | "
            f"X: {hz.x_min}..{hz.x_max} | Y: {hz.y_min}..{hz.y_max} | "
            f"Threshold: {g.swipe_threshold_px}px | Action: {g.action.type}"
        )

    print("\n[INFO] Touch the screen or swipe upward from the bottom edge.")
    print("[INFO] Press Ctrl+C to exit.\n" + "-" * 65)

    def test_log(msg: str):
        print(f"  -> {msg}")

    dispatcher = ActionDispatcher()
    configured_gestures = []
    for g in cfg.gestures:
        if not g.enabled:
            continue
        # In test mode, we can optionally trigger or dry-run
        if args.dry_run:
            trigger_fn = lambda g_name=g.name: print(f"  *** [DRY-RUN MATCH] {g_name} would fire! ***")
        else:
            trigger_obj = dispatcher.create_trigger(g.action)
            trigger_fn = trigger_obj.trigger
        configured_gestures.append((g, trigger_fn))

    detector = GestureDetector(
        screen_width=width,
        screen_height=height,
        gestures=configured_gestures,
        debounce_seconds=cfg.debounce_seconds,
        on_touch_debug=test_log,
    )

    try:
        while True:
            r, _, _ = select.select([dev.fd], [], [], 1.0)
            if not r:
                continue
            for event in dev.read():
                detector.process_event(event)
    except KeyboardInterrupt:
        print("\nExiting touch test monitor.")
    finally:
        dispatcher.close()
        dev.close()


def cmd_trigger(args):
    """Manually test triggering the Steam keyboard or chord."""
    from .actions import (
        ActionConfig,
        ActionDispatcher,
        KeyboardChordTrigger,
        SteamChordTrigger,
        SteamUrlTrigger,
    )

    setup_logging(True)
    action_type = args.action.lower()
    print(f"\n[INFO] Testing manual action trigger: '{action_type}'...")

    if action_type == "steam_chord":
        print("Creating virtual gamepad and injecting Steam Guide + X chord...")
        t = SteamChordTrigger(chord_buttons=["BTN_MODE", "BTN_X"])
        success = t.trigger()
        t.close()
    elif action_type == "steam_url":
        print("Invoking `steam steam://open/keyboard`...")
        t = SteamUrlTrigger()
        success = t.trigger()
    elif action_type == "desktop_osk":
        print("Toggling native desktop on-screen keyboard (GNOME/KDE)...")
        from .actions import toggle_desktop_osk
        success = toggle_desktop_osk()
    elif action_type in ("auto", "auto_keyboard"):
        print("Running intelligent session-aware keyboard trigger...")
        disp = ActionDispatcher()
        trig = disp.create_trigger(ActionConfig(type="auto"))
        success = trig.trigger()
        disp.close()
    elif action_type == "keyboard_chord":
        print("Injecting Super + X keyboard chord...")
        t = KeyboardChordTrigger(key_names=["KEY_LEFTMETA", "KEY_X"])
        success = t.trigger()
        t.close()
    else:
        print(f"[ERROR] Unknown action type: {action_type}")
        return

    if success:
        print("[SUCCESS] Action emitted successfully!\n")
    else:
        print("[FAILURE] Failed to emit action.\n")


def cmd_devices(args):
    """List all connected input devices and identify touchscreens."""
    from .device import get_screen_bounds, list_touch_devices

    print("=" * 70)
    print(" CONNECTED INPUT DEVICES")
    print("=" * 70)
    devs = list_touch_devices()
    for dev, is_touch in devs:
        flag = "[TOUCHSCREEN]" if is_touch else "             "
        print(f" {flag} {dev.path:20} {dev.name}")
        if is_touch:
            w, h = get_screen_bounds(dev)
            print(f"                  Resolution: {w} x {h}")
    print("=" * 70)


def cmd_install_service(args):
    """Install and enable systemd user service."""
    USER_SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    service_path = USER_SYSTEMD_DIR / SYSTEMD_SERVICE_NAME

    # Source service template
    repo_root = Path(__file__).resolve().parent.parent
    src_service = repo_root / "systemd" / SYSTEMD_SERVICE_NAME

    if not src_service.exists():
        print(f"[ERROR] Service definition file not found at {src_service}")
        sys.exit(1)

    content = src_service.read_text()
    service_path.write_text(content)
    print(f"[OK] Wrote service unit to {service_path}")

    # Install desktop launcher
    src_desktop = repo_root / "systemd" / DESKTOP_ENTRY_NAME
    if src_desktop.exists():
        USER_APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
        dest_desktop = USER_APPLICATIONS_DIR / DESKTOP_ENTRY_NAME
        desktop_content = src_desktop.read_text()
        exec_cmd = (
            f"sh -c 'PATH=\"$HOME/.local/bin:$PATH\" "
            f"PYTHONPATH=\"{repo_root}:$PYTHONPATH\" python3 -m edge_gestures gui'"
        )
        lines = []
        for line in desktop_content.splitlines():
            if line.startswith("Exec="):
                lines.append(f"Exec={exec_cmd}")
            else:
                lines.append(line)
        dest_desktop.write_text("\n".join(lines) + "\n")
        dest_desktop.chmod(0o755)
        subprocess.run(
            ["update-desktop-database", str(USER_APPLICATIONS_DIR)],
            check=False,
            capture_output=True,
        )
        print(f"[OK] Installed desktop launcher to {dest_desktop}")

    # Reload systemd and enable
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", SYSTEMD_SERVICE_NAME], check=True)
        print(f"[SUCCESS] Service {SYSTEMD_SERVICE_NAME} installed, enabled, and started!")
        print("\nCheck status with: systemctl --user status edge-gestures.service\n")
    except Exception as e:
        print(f"[ERROR] Failed to enable systemd user service: {e}")


def cmd_uninstall_service(args):
    """Disable and remove systemd user service."""
    service_path = USER_SYSTEMD_DIR / SYSTEMD_SERVICE_NAME
    try:
        subprocess.run(["systemctl", "--user", "stop", SYSTEMD_SERVICE_NAME], check=False)
        subprocess.run(["systemctl", "--user", "disable", SYSTEMD_SERVICE_NAME], check=False)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    except Exception:
        pass

    if service_path.exists():
        service_path.unlink()
        print(f"[OK] Removed service file {service_path}")

    desktop_path = USER_APPLICATIONS_DIR / DESKTOP_ENTRY_NAME
    if desktop_path.exists():
        desktop_path.unlink()
        subprocess.run(
            ["update-desktop-database", str(USER_APPLICATIONS_DIR)],
            check=False,
            capture_output=True,
        )
        print(f"[OK] Removed desktop launcher {desktop_path}")

    print(f"[SUCCESS] Service {SYSTEMD_SERVICE_NAME} uninstalled.")


def cmd_status(args):
    """Check service status."""
    subprocess.run(["systemctl", "--user", "status", SYSTEMD_SERVICE_NAME, "--no-pager"])


def cmd_gui(args):
    """Launch configuration GUI (Lotus-GUI Servo 0.7.0 or GTK4 / Libadwaita)."""
    import shutil

    config_path = Path(args.config) if getattr(args, "config", None) else None
    cfg = load_config(config_path)

    # Determine backend: CLI flag overrides saved config preference
    backend = getattr(args, "backend", None)
    if not backend:
        backend = getattr(cfg, "gui_backend", "lotus").lower()

    if backend == "lotus":
        lotus_script = Path(__file__).resolve().parent.parent / "gui-lotus" / "main.js"
        node_bin = shutil.which("node")

        if node_bin and lotus_script.exists():
            cmd = [node_bin, str(lotus_script)]
            if config_path:
                cmd.extend(["-c", str(config_path)])
            
            env = os.environ.copy()
            # Ensure static TLS allocation for Servo native bindings on Linux
            tunables = env.get("GLIBC_TUNABLES", "")
            if "optional_static_tls" not in tunables:
                env["GLIBC_TUNABLES"] = f"{tunables}:glibc.rtld.optional_static_tls=16384" if tunables else "glibc.rtld.optional_static_tls=16384"
            env["LOTUS_TLS_FIXED"] = "1"

            try:
                res = subprocess.run(cmd, env=env)
                sys.exit(res.returncode)
            except Exception as e:
                print(f"[WARN] Lotus-GUI failed to launch: {e}. Falling back to GTK4 GUI...")
        else:
            print("[WARN] Node.js or Lotus-GUI script not found. Falling back to GTK4 GUI...")

    # Fallback / GTK4 GUI
    try:
        from .gui import main as gui_main
    except Exception as e:
        print(f"[ERROR] Could not start GTK GUI: {e}")
        print("Please ensure PyGObject and Libadwaita are installed (e.g. 'python3-gobject' and 'libadwaita').")
        sys.exit(1)

    sys.exit(gui_main(config_path=config_path))


def main():
    parser = argparse.ArgumentParser(
        prog="edge-gestures",
        description="Edge Gestures background service for Linux handhelds (ROG Ally, Steam Deck)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # gui / config
    p_gui = subparsers.add_parser(
        "gui",
        aliases=["config"],
        help="Launch graphical configuration app (Lotus-GUI Servo 0.7.0 or GTK4)",
    )
    p_gui.add_argument("-c", "--config", type=str, help="Path to config file")
    p_gui.add_argument(
        "--backend",
        type=str,
        choices=["lotus", "gtk"],
        help="GUI backend to launch (default: saved config preference or lotus)",
    )

    # run
    p_run = subparsers.add_parser("run", help="Run the daemon")
    p_run.add_argument("-c", "--config", type=str, help="Path to config file")

    # test
    p_test = subparsers.add_parser("test", help="Test monitor displaying touches & gestures")
    p_test.add_argument("-c", "--config", type=str, help="Path to config file")
    p_test.add_argument("--dry-run", action="store_true", help="Do not trigger actions on gesture match")

    # trigger
    p_trig = subparsers.add_parser("trigger", help="Manually trigger an action (steam_chord, steam_url, keyboard_chord)")
    p_trig.add_argument(
        "--action",
        type=str,
        default="auto",
        choices=["auto", "steam_chord", "steam_url", "desktop_osk", "keyboard_chord"],
        help="Action to fire (default: auto)",
    )

    # devices
    subparsers.add_parser("devices", help="List input devices and detected touchscreens")

    # install-service
    subparsers.add_parser("install-service", help="Install and start systemd user service")

    # uninstall-service
    subparsers.add_parser("uninstall-service", help="Stop and remove systemd user service")

    # status
    subparsers.add_parser("status", help="Check systemd service status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command in ("gui", "config"):
        cmd_gui(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "trigger":
        cmd_trigger(args)
    elif args.command == "devices":
        cmd_devices(args)
    elif args.command == "install-service":
        cmd_install_service(args)
    elif args.command == "uninstall-service":
        cmd_uninstall_service(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
