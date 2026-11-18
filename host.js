'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const net = require('net');
const { spawnSync } = require('child_process');
const YAML = require('yaml');

const SERVICE_NAME = 'edge-gestures.service';
const USER_SYSTEMD_DIR = path.join(os.homedir(), '.config', 'systemd', 'user');
const SERVICE_PATH = path.join(USER_SYSTEMD_DIR, SERVICE_NAME);
const CONFIG_PATH = path.join(os.homedir(), '.config', 'edge-gestures', 'config.yaml');

const DEFAULT_CONFIG = {
  gui_backend: 'lotus',
  device: {
    path: 'auto',
    name: '',
    phys: '',
    name_filters: ['touch', 'goodix', 'nvtk', 'elan', 'fts', 'ilitek', 'focaltech', 'atmel'],
  },
  debounce_seconds: 0.6,
  gestures: [
    {
      name: 'bottom_open_keyboard',
      enabled: true,
      edge: 'bottom',
      direction: 'up',
      edge_depth_px: 45,
      span_start_ratio: 0.20,
      span_end_ratio: 0.80,
      swipe_threshold_px: 35,
      max_deviation_px: 90,
      max_duration: 0.35,
      action: {
        type: 'auto',
        chord: ['BTN_MODE', 'BTN_X'],
        keys: ['KEY_LEFTMETA', 'KEY_X'],
        url: 'steam://open/keyboard',
        command: '',
        press_duration: 0.06,
      },
    },
  ],
};

function getRuntimeDir() {
  return process.env.XDG_RUNTIME_DIR || path.join('/run/user', String(process.getuid ? process.getuid() : 1000));
}

function getSocketPath() {
  return path.join(getRuntimeDir(), 'atrium-edge-gestures.sock');
}

function getBinaryPath() {
  const onedirBin = path.join(__dirname, 'bin', 'edge-gestures-dist', 'edge-gestures');
  if (fs.existsSync(onedirBin)) return onedirBin;
  const directBin = path.join(__dirname, 'bin', 'edge-gestures');
  if (fs.existsSync(directBin)) return directBin;
  return 'edge-gestures';
}

function getServiceState() {
  const installed = fs.existsSync(SERVICE_PATH);
  if (!installed) {
    return { installed: false, active: false, enabled: false };
  }
  const activeRes = spawnSync('systemctl', ['--user', 'is-active', SERVICE_NAME], { encoding: 'utf8' });
  const enabledRes = spawnSync('systemctl', ['--user', 'is-enabled', SERVICE_NAME], { encoding: 'utf8' });
  return {
    installed: true,
    active: (activeRes.stdout || '').trim() === 'active',
    enabled: (enabledRes.stdout || '').trim() === 'enabled',
  };
}

function handleServiceAction(action) {
  try {
    switch (action) {
      case 'start': {
        const res = spawnSync('systemctl', ['--user', 'start', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'stop': {
        const res = spawnSync('systemctl', ['--user', 'stop', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'restart': {
        const res = spawnSync('systemctl', ['--user', 'restart', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'enable': {
        const res = spawnSync('systemctl', ['--user', 'enable', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'disable': {
        const res = spawnSync('systemctl', ['--user', 'disable', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'install': {
        fs.mkdirSync(USER_SYSTEMD_DIR, { recursive: true });
        const binPath = getBinaryPath();
        if (fs.existsSync(binPath)) {
          try {
            fs.chmodSync(binPath, 0o755);
          } catch (_) {}
        }
        const unit = `[Unit]
Description=Edge Gestures Daemon (Atrium Plugin)
Documentation=https://github.com/
After=default.target
Wants=default.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStart=${binPath} run
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
`;
        fs.writeFileSync(SERVICE_PATH, unit, 'utf8');
        spawnSync('systemctl', ['--user', 'daemon-reload']);
        const res = spawnSync('systemctl', ['--user', 'enable', '--now', SERVICE_NAME], { encoding: 'utf8' });
        return { success: res.status === 0, error: res.stderr || '' };
      }
      case 'uninstall': {
        spawnSync('systemctl', ['--user', 'disable', '--now', SERVICE_NAME]);
        if (fs.existsSync(SERVICE_PATH)) {
          fs.unlinkSync(SERVICE_PATH);
        }
        spawnSync('systemctl', ['--user', 'daemon-reload']);
        return { success: true };
      }
      default:
        return { success: false, error: `Unknown action ${action}` };
    }
  } catch (err) {
    return { success: false, error: err.message };
  }
}

function readConfig() {
  try {
    if (!fs.existsSync(CONFIG_PATH)) {
      const dir = path.dirname(CONFIG_PATH);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(CONFIG_PATH, YAML.stringify(DEFAULT_CONFIG, { indent: 2 }), 'utf8');
      return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
    }
    const content = fs.readFileSync(CONFIG_PATH, 'utf8');
    const parsed = YAML.parse(content) || {};
    return {
      gui_backend: parsed.gui_backend || 'lotus',
      device: {
        path: parsed.device?.path || 'auto',
        name: parsed.device?.name || '',
        phys: parsed.device?.phys || '',
        name_filters: parsed.device?.name_filters || DEFAULT_CONFIG.device.name_filters,
      },
      debounce_seconds: typeof parsed.debounce_seconds === 'number' ? parsed.debounce_seconds : 0.6,
      gestures: Array.isArray(parsed.gestures) && parsed.gestures.length > 0 ? parsed.gestures : DEFAULT_CONFIG.gestures,
    };
  } catch (e) {
    console.error('[atrium-edge-gestures] Error reading config:', e.message);
    return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  }
}

function writeConfig(data) {
  try {
    const dir = path.dirname(CONFIG_PATH);
    fs.mkdirSync(dir, { recursive: true });
    const yamlString = YAML.stringify(data, { indent: 2 });
    fs.writeFileSync(CONFIG_PATH, yamlString, 'utf8');

    // Dynamic SIGHUP reload without restarting daemon
    const reload = spawnSync('systemctl', ['--user', 'reload', SERVICE_NAME]);
    if (reload.status !== 0) {
      spawnSync('pkill', ['-HUP', '-f', 'edge-gestures']);
    }
    return { success: true, path: CONFIG_PATH };
  } catch (e) {
    console.error('[atrium-edge-gestures] Error writing config:', e.message);
    return { success: false, error: e.message };
  }
}

function detectInputDevices() {
  const list = [{ name: 'Auto-detect Touchscreen', path: 'auto', isTouch: true, stablePath: 'auto' }];
  try {
    // Map event handler to by-path symlink
    const byPathMap = {};
    const byPathDir = '/dev/input/by-path';
    if (fs.existsSync(byPathDir)) {
      const entries = fs.readdirSync(byPathDir);
      for (const entry of entries) {
        try {
          const full = path.join(byPathDir, entry);
          const target = fs.readlinkSync(full);
          const eventMatch = target.match(/event\d+/);
          if (eventMatch) {
            byPathMap[eventMatch[0]] = full;
          }
        } catch (_) {}
      }
    }

    if (fs.existsSync('/proc/bus/input/devices')) {
      const content = fs.readFileSync('/proc/bus/input/devices', 'utf8');
      const blocks = content.trim().split('\n\n');
      for (const b of blocks) {
        const nameMatch = b.match(/N: Name="([^"]+)"/);
        const physMatch = b.match(/P: Phys=([^\n]+)/);
        const handlerMatch = b.match(/H: Handlers=.*?(event\d+)/);
        const hasAbs = /B: ABS=/.test(b);
        const name = nameMatch ? nameMatch[1] : '';
        const phys = physMatch ? physMatch[1].trim() : '';
        const event = handlerMatch ? handlerMatch[1] : '';
        if (!event) continue;

        const isTouch = /touch|goodix|nvtk|elan|fts|ilitek|focaltech|atmel/i.test(name) || (hasAbs && /touch|mouse/i.test(b));
        if (isTouch) {
          const stablePath = byPathMap[event] || `/dev/input/${event}`;
          list.push({
            name: `${name} (${event})`,
            rawName: name,
            phys: phys,
            path: stablePath,
            eventNode: `/dev/input/${event}`,
            isTouch: true,
          });
        }
      }
    }
  } catch (err) {
    console.warn('[atrium-edge-gestures] Could not parse input devices:', err.message);
  }
  return list;
}

let socketServer = null;

function setupAtriumSocket(ctx) {
  const sockPath = getSocketPath();
  try {
    if (fs.existsSync(sockPath)) {
      fs.unlinkSync(sockPath);
    }
  } catch (_) {}

  socketServer = net.createServer((c) => {
    c.on('data', () => {
      ctx.log('[atrium-edge-gestures] Edge gesture ping received via domain socket!');
      try {
        if (ctx.shell && typeof ctx.shell.toggleOsk === 'function') {
          ctx.shell.toggleOsk();
        } else if (typeof ctx.shell?.applyOsk === 'function') {
          ctx.shell.applyOsk(true);
        }
      } catch (err) {
        ctx.log('[atrium-edge-gestures] Shell OSK toggle error:', err.message);
      }
    });
  });

  socketServer.on('error', (err) => {
    ctx.log('[atrium-edge-gestures] Socket server error:', err.message);
  });

  socketServer.listen(sockPath, () => {
    try {
      fs.chmodSync(sockPath, 0o777);
    } catch (_) {}
    ctx.log('[atrium-edge-gestures] Listening for gestures on socket:', sockPath);
  });
}

function cleanupAtriumSocket() {
  if (socketServer) {
    try {
      socketServer.close();
    } catch (_) {}
    socketServer = null;
  }
  const sockPath = getSocketPath();
  try {
    if (fs.existsSync(sockPath)) fs.unlinkSync(sockPath);
  } catch (_) {}
}

async function activate(ctx) {
  setupAtriumSocket(ctx);

  function pushState() {
    ctx.ipc.send('state-update', {
      service: getServiceState(),
      config: readConfig(),
      devices: detectInputDevices(),
    });
  }

  await ctx.registerContribution({
    id: 'config',
    label: 'Edge Gestures',
    icon: '✋',
    sortKey: 35,
    content: { kind: 'servo', entry: 'ui/index.html' },
    input: { mode: 'pointer' },
    onFocusChange(focused) {
      if (focused) pushState();
    },
  });

  ctx.ipc.on('get-state', () => {
    pushState();
  });

  ctx.ipc.on('service-action', ({ action }) => {
    const result = handleServiceAction(action);
    ctx.ipc.send('action-result', { action, ...result });
    pushState();
  });

  ctx.ipc.on('save-config', (newConfig) => {
    const res = writeConfig(newConfig);
    ctx.ipc.send('save-result', res);
    pushState();
  });

  // Staggered state pushes during startup load to ensure pane picks up state
  setTimeout(pushState, 300);
  setTimeout(pushState, 1200);
  setTimeout(pushState, 2500);

  ctx.log('Edge Gestures plugin activated.');
}

async function deactivate(ctx) {
  cleanupAtriumSocket();
  if (ctx && typeof ctx.disposeAll === 'function') {
    ctx.disposeAll();
  }
}

module.exports = { activate, deactivate };
