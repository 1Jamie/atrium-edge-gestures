# atrium-edge-gestures

Edge Gestures daemon and overlay configuration plugin for [Atrium](https://github.com/1Jamie/Atrium) on Linux handhelds (ROG Ally, Steam Deck, Legion Go).

Provides passive touchscreen edge-swipe detection to trigger on-screen keyboards (Steam OSK, Atrium native OSK, GNOME, KDE) and system actions without interfering with primary gamepad inputs.

---

## Features

- **Zero-Device IPC (No Seat Hijacking)**: Unlike virtual controller/keyboard emulators that steal Seat 1 in games like *Call of Duty: Black Ops 3*, `edge-gestures` emits triggers over lightweight IPC:
  - **Atrium Unix Domain Socket**: Ping `$XDG_RUNTIME_DIR/atrium-edge-gestures.sock` to trigger Atrium's native `triggerOsk()`.
  - **Non-blocking Steam Pipe**: Writes `open steam://open/keyboard` directly to `~/.steam/steam.pipe` without spawning subprocesses or blocking if Steam exits.
  - **Desktop D-Bus Fallback**: Toggles GNOME and KDE virtual keyboards when running on the desktop.
- **Dynamic On-The-Fly Reload (SIGHUP)**: Slider adjustments apply instantly to the running daemon without restarting the service or dropping touchscreen focus.
- **Embedded Lifecycle Management**: Control the background service directly from Atrium's overlay:
  - **Start / Stop / Restart** buttons.
  - **Autostart on Boot** toggle (manages `systemd --user`).
  - **Touch-safe Uninstall**: Two-stage confirmation dialog prevents accidental service removal while tapping on handheld screens.
- **Stable Hardware Discovery**: Auto-detects handheld touchscreens (e.g. `NVTK0603:00` on ROG Ally) using persistent `/dev/input/by-path/` symlinks and device attributes so configurations survive reboots and dock disconnects.
- **Self-Contained Standalone Runtime**: Bundles a standalone PyInstaller binary (`--onedir`) in `bin/edge-gestures-dist/`, running cleanly on SteamOS, Bazzite, and CachyOS with zero host Python or virtual environment dependencies.

---

## Installation

Ensure Atrium is installed so `atrium` is available on your `PATH`.

### From Repository Directory

```bash
atrium --install-plugin /path/to/atrium-edge-gestures
```

### From Release Zip

```bash
atrium --install-plugin edge-gestures-1.0.0.zip
```

*From an Atrium checkout, `npx atrium-dev install plugin <dir|zip>` can also be used.*

### Removing the Plugin

```bash
atrium --remove-plugin edge-gestures
```

---

## Building from Source

The background daemon source is maintained in [`edge-gestures`](https://github.com/1Jamie/edge-gestures). To recompile the standalone binary distribution into this plugin:

```bash
cd /path/to/edge-gestures
./build-binary.sh
```

This compiles the Python daemon into `atrium-edge-gestures/bin/edge-gestures-dist/` using PyInstaller's `--onedir` mode.

To pack the plugin for distribution:

```bash
cd /path/to/atrium
npx atrium-dev pack plugin /path/to/atrium-edge-gestures
```

---

## License

MIT
