/**
 * Edge Gestures Atrium Plugin UI Logic
 */

let state = {
  service: { installed: false, active: false, enabled: false },
  config: null,
  devices: [],
};

function sendHost(channel, payload = {}) {
  if (window.AtriumPlugin && typeof window.AtriumPlugin.send === 'function') {
    window.AtriumPlugin.send(channel, payload);
  } else if (window.lotus?.ipc?.send) {
    window.lotus.ipc.send('atrium-plugin-ipc', { plugin: 'edge-gestures', channel, data: payload });
  } else if (window.lotus?.send) {
    window.lotus.send('atrium-plugin-ipc', { plugin: 'edge-gestures', channel, data: payload });
  }
}

function onHost(channel, callback) {
  if (window.AtriumPlugin && typeof window.AtriumPlugin.on === 'function') {
    window.AtriumPlugin.on(channel, callback);
  }
}

// Elements
const serviceStatusBadge = document.getElementById('service-status-badge');
const serviceStatusDot = serviceStatusBadge.querySelector('.status-dot');
const serviceStatusText = document.getElementById('service-status-text');
const autostartBadge = document.getElementById('autostart-status-badge');
const serviceDetails = document.getElementById('service-details-text');

const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnRestart = document.getElementById('btn-restart');
const btnAutostart = document.getElementById('btn-autostart');
const btnInstall = document.getElementById('btn-install');
const btnUninstall = document.getElementById('btn-uninstall');
const btnSave = document.getElementById('btn-save');

const cfgDeviceSelect = document.getElementById('cfg-device-select');
const cfgDebounce = document.getElementById('cfg-debounce');
const cfgDebounceVal = document.getElementById('cfg-debounce-val');
const cfgTriggerType = document.getElementById('cfg-trigger-type');
const gesturesList = document.getElementById('gestures-list');

// Canvas
const canvas = document.getElementById('hotzone-canvas');
const ctx = canvas.getContext('2d');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupRangeInputs();
  setupActionListeners();

  // Wire AtriumPlugin IPC listeners
  let wired = false;
  function wirePlugin() {
    if (wired) return;
    if (window.AtriumPlugin && typeof window.AtriumPlugin.on === 'function') {
      wired = true;
      onHost('state-update', onStateUpdate);
      onHost('action-result', onActionResult);
      onHost('save-result', onSaveResult);
      sendHost('get-state');
    }
  }

  // Also listen directly on window for CustomEvents dispatched by the bridge
  window.addEventListener('plugin:edge-gestures:state-update', (e) => onStateUpdate(e.detail));
  window.addEventListener('plugin:edge-gestures:action-result', (e) => onActionResult(e.detail));
  window.addEventListener('plugin:edge-gestures:save-result', (e) => onSaveResult(e.detail));

  // Request state whenever the tab is shown
  window.addEventListener('atrium-pane-shown', () => {
    sendHost('get-state');
  });

  const checkPluginReady = setInterval(() => {
    wirePlugin();
    if (wired && state.config) {
      clearInterval(checkPluginReady);
    }
  }, 100);

  // Poll for state until we get initial config
  const statePoll = setInterval(() => {
    if (state.config) {
      clearInterval(statePoll);
      return;
    }
    wirePlugin();
    sendHost('get-state');
  }, 400);

  // Periodic heartbeat every 3 seconds to keep status live
  setInterval(() => {
    sendHost('get-state');
  }, 3000);

  wirePlugin();
  sendHost('get-state');
});

function setupTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  const panes = document.querySelectorAll('.tab-pane');

  tabs.forEach((t) => {
    t.addEventListener('click', () => {
      tabs.forEach((tab) => tab.classList.remove('active'));
      panes.forEach((p) => p.classList.remove('active'));

      t.classList.add('active');
      const targetId = t.getAttribute('data-tab');
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add('active');
        if (targetId === 'tab-visualizer') {
          drawHotzones();
        }
      }
    });
  });
}

function setupRangeInputs() {
  cfgDebounce.addEventListener('input', (e) => {
    cfgDebounceVal.textContent = `${e.target.value}s`;
  });
}

function setupActionListeners() {
  btnStart.addEventListener('click', () => {
    btnStart.disabled = true;
    sendHost('service-action', { action: 'start' });
  });

  btnStop.addEventListener('click', () => {
    btnStop.disabled = true;
    sendHost('service-action', { action: 'stop' });
  });

  btnRestart.addEventListener('click', () => {
    btnRestart.disabled = true;
    sendHost('service-action', { action: 'restart' });
  });

  btnAutostart.addEventListener('click', () => {
    btnAutostart.disabled = true;
    const nextAction = state.service.enabled ? 'disable' : 'enable';
    sendHost('service-action', { action: nextAction });
  });

  btnInstall.addEventListener('click', () => {
    btnInstall.disabled = true;
    sendHost('service-action', { action: 'install' });
  });

  let uninstallConfirmTimer = null;
  btnUninstall.addEventListener('click', () => {
    if (!btnUninstall.dataset.confirming) {
      btnUninstall.dataset.confirming = 'true';
      btnUninstall.innerHTML = '<span class="btn-icon">⚠️</span> Confirm Uninstall?';
      btnUninstall.classList.add('confirming');
      uninstallConfirmTimer = setTimeout(() => {
        delete btnUninstall.dataset.confirming;
        btnUninstall.innerHTML = '<span class="btn-icon">🗑️</span> Uninstall Service';
        btnUninstall.classList.remove('confirming');
      }, 3500);
      return;
    }

    if (uninstallConfirmTimer) {
      clearTimeout(uninstallConfirmTimer);
      uninstallConfirmTimer = null;
    }
    delete btnUninstall.dataset.confirming;
    btnUninstall.classList.remove('confirming');
    btnUninstall.disabled = true;
    btnUninstall.textContent = 'Uninstalling...';
    sendHost('service-action', { action: 'uninstall' });
  });

  btnSave.addEventListener('click', () => {
    saveConfiguration();
  });
}

function onStateUpdate(data) {
  if (!data) return;
  state = { ...state, ...data };
  renderServiceState();
  if (data.devices) renderDevices();
  if (data.config) renderConfig();
  drawHotzones();
}

function onActionResult(result) {
  if (result && !result.success && result.error) {
    if (window.AtriumPlugin && typeof window.AtriumPlugin.notify === 'function') {
      window.AtriumPlugin.notify({
        title: 'Edge Gestures',
        body: `Service action failed: ${result.error}`,
        urgency: 'critical',
      });
    } else {
      serviceDetails.textContent = `Error: ${result.error}`;
      serviceDetails.style.color = 'var(--atrium-danger, #f87171)';
    }
  }
}

function onSaveResult(result) {
  if (result && result.success) {
    btnSave.textContent = '✓ Saved & Applied!';
    btnSave.style.borderColor = 'var(--accent-color)';
    setTimeout(() => {
      btnSave.innerHTML = '<span class="btn-icon">💾</span> Save &amp; Apply';
      btnSave.style.borderColor = '';
    }, 1800);
  }
}

function renderServiceState() {
  const s = state.service || {};
  serviceStatusDot.className = 'status-dot';

  if (!s.installed) {
    serviceStatusDot.classList.add('missing');
    serviceStatusText.textContent = 'Not Installed';
    autostartBadge.textContent = 'Autostart: —';
    serviceDetails.textContent = 'Service unit is not yet installed in systemd user space.';

    btnInstall.style.display = 'inline-flex';
    btnInstall.disabled = false;
    btnStart.style.display = 'none';
    btnStop.style.display = 'none';
    btnRestart.style.display = 'none';
    btnAutostart.style.display = 'none';
    btnUninstall.disabled = true;
    btnUninstall.innerHTML = '<span class="btn-icon">🗑️</span> Uninstall Service';
    delete btnUninstall.dataset.confirming;
    btnUninstall.classList.remove('confirming');
  } else {
    btnInstall.style.display = 'none';
    btnStart.style.display = 'inline-flex';
    btnStop.style.display = 'inline-flex';
    btnRestart.style.display = 'inline-flex';
    btnAutostart.style.display = 'inline-flex';
    btnUninstall.disabled = false;
    if (!btnUninstall.dataset.confirming) {
      btnUninstall.innerHTML = '<span class="btn-icon">🗑️</span> Uninstall Service';
      btnUninstall.classList.remove('confirming');
    }

    if (s.active) {
      serviceStatusDot.classList.add('active');
      serviceStatusText.textContent = 'Running';
      serviceDetails.textContent = 'Passive touchscreen edge monitoring daemon is active.';
      btnStart.disabled = true;
      btnStop.disabled = false;
      btnRestart.disabled = false;
    } else {
      serviceStatusDot.classList.add('inactive');
      serviceStatusText.textContent = 'Stopped';
      serviceDetails.textContent = 'Daemon is stopped. Touch edge gestures are currently inactive.';
      btnStart.disabled = false;
      btnStop.disabled = true;
      btnRestart.disabled = true;
    }

    autostartBadge.textContent = s.enabled ? 'Autostart: Enabled' : 'Autostart: Disabled';
    btnAutostart.disabled = false;
    btnAutostart.innerHTML = s.enabled
      ? '<span class="btn-icon">⚙</span> Disable Autostart'
      : '<span class="btn-icon">⚙</span> Enable Autostart';
  }
}

function renderDevices() {
  const currentVal = state.config?.device?.path || 'auto';
  cfgDeviceSelect.innerHTML = '';

  const autoOpt = document.createElement('option');
  autoOpt.value = 'auto';
  autoOpt.textContent = 'Auto-detect Touchscreen (Recommended)';
  cfgDeviceSelect.appendChild(autoOpt);

  (state.devices || []).forEach((d) => {
    if (d.path === 'auto') return;
    const opt = document.createElement('option');
    opt.value = d.path;
    opt.textContent = `${d.name} (${d.path})`;
    if (d.rawName) opt.setAttribute('data-name', d.rawName);
    if (d.phys) opt.setAttribute('data-phys', d.phys);
    cfgDeviceSelect.appendChild(opt);
  });

  cfgDeviceSelect.value = currentVal;
}

function renderConfig() {
  const cfg = state.config;
  if (!cfg) return;

  if (typeof cfg.debounce_seconds === 'number') {
    cfgDebounce.value = cfg.debounce_seconds;
    cfgDebounceVal.textContent = `${cfg.debounce_seconds}s`;
  }

  const gList = Array.isArray(cfg.gestures) ? cfg.gestures : [];
  gesturesList.innerHTML = '';

  gList.forEach((g, idx) => {
    const item = document.createElement('div');
    item.className = 'gesture-item';
    item.innerHTML = `
      <div class="gesture-header">
        <span class="gesture-title">${g.name || 'Gesture ' + (idx + 1)}</span>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;">
          <input type="checkbox" id="g-enabled-${idx}" ${g.enabled !== false ? 'checked' : ''}>
          <span>Enabled</span>
        </label>
      </div>
      <div class="gesture-grid">
        <div class="input-group">
          <label class="input-label">Screen Edge</label>
          <select id="g-edge-${idx}" class="form-select atrium-touch-target">
            <option value="bottom" ${g.edge === 'bottom' ? 'selected' : ''}>Bottom Edge</option>
            <option value="top" ${g.edge === 'top' ? 'selected' : ''}>Top Edge</option>
            <option value="left" ${g.edge === 'left' ? 'selected' : ''}>Left Edge</option>
            <option value="right" ${g.edge === 'right' ? 'selected' : ''}>Right Edge</option>
          </select>
        </div>
        <div class="input-group">
          <label class="input-label">Swipe Direction</label>
          <select id="g-dir-${idx}" class="form-select atrium-touch-target">
            <option value="up" ${g.direction === 'up' ? 'selected' : ''}>Swipe Up</option>
            <option value="down" ${g.direction === 'down' ? 'selected' : ''}>Swipe Down</option>
            <option value="left" ${g.direction === 'left' ? 'selected' : ''}>Swipe Left</option>
            <option value="right" ${g.direction === 'right' ? 'selected' : ''}>Swipe Right</option>
          </select>
        </div>
        <div class="input-group">
          <label class="input-label">Hotzone Depth (${g.edge_depth_px || 45}px)</label>
          <input type="number" id="g-depth-${idx}" class="form-input atrium-touch-target" value="${g.edge_depth_px || 45}" min="20" max="150">
        </div>
        <div class="input-group">
          <label class="input-label">Swipe Distance Threshold (${g.swipe_threshold_px || 35}px)</label>
          <input type="number" id="g-thresh-${idx}" class="form-input atrium-touch-target" value="${g.swipe_threshold_px || 35}" min="15" max="200">
        </div>
      </div>
    `;
    gesturesList.appendChild(item);

    // Redraw hotzones on any gesture change
    item.querySelectorAll('select, input').forEach((el) => {
      el.addEventListener('change', drawHotzones);
    });
  });

  const firstActionType = gList[0]?.action?.type || 'auto';
  cfgTriggerType.value = firstActionType;
}

function saveConfiguration() {
  const selectedOpt = cfgDeviceSelect.options[cfgDeviceSelect.selectedIndex];
  const selectedPath = cfgDeviceSelect.value || 'auto';
  const selectedName = selectedOpt?.getAttribute('data-name') || '';
  const selectedPhys = selectedOpt?.getAttribute('data-phys') || '';

  const newConfig = {
    gui_backend: 'lotus',
    device: {
      path: selectedPath,
      name: selectedName,
      phys: selectedPhys,
      name_filters: state.config?.device?.name_filters || ['touch', 'goodix', 'nvtk', 'elan'],
    },
    debounce_seconds: parseFloat(cfgDebounce.value) || 0.6,
    gestures: (state.config?.gestures || []).map((orig, idx) => {
      const edge = document.getElementById(`g-edge-${idx}`)?.value || orig.edge || 'bottom';
      const dir = document.getElementById(`g-dir-${idx}`)?.value || orig.direction || 'up';
      const depth = parseInt(document.getElementById(`g-depth-${idx}`)?.value, 10) || orig.edge_depth_px || 45;
      const thresh = parseInt(document.getElementById(`g-thresh-${idx}`)?.value, 10) || orig.swipe_threshold_px || 35;
      const enabled = document.getElementById(`g-enabled-${idx}`)?.checked ?? orig.enabled;

      return {
        ...orig,
        enabled: Boolean(enabled),
        edge: edge,
        direction: dir,
        edge_depth_px: depth,
        swipe_threshold_px: thresh,
        action: {
          ...orig.action,
          type: cfgTriggerType.value || 'auto',
          url: 'steam://open/keyboard',
        },
      };
    }),
  };

  sendHost('save-config', newConfig);
}

function drawHotzones() {
  if (!canvas || !ctx) return;
  const w = canvas.width;
  const h = canvas.height;

  // Background
  ctx.fillStyle = '#090d13';
  ctx.fillRect(0, 0, w, h);

  // Screen frame
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 4;
  ctx.strokeRect(4, 4, w - 8, h - 8);

  // Label center
  ctx.fillStyle = '#64748b';
  ctx.font = '14px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Touchscreen Display Area', w / 2, h / 2);

  const gestures = state.config?.gestures || [];
  gestures.forEach((g) => {
    if (!g.enabled) return;

    ctx.fillStyle = 'rgba(45, 212, 191, 0.35)';
    ctx.strokeStyle = '#2dd4bf';
    ctx.lineWidth = 2;

    const startRatio = g.span_start_ratio ?? 0.2;
    const endRatio = g.span_end_ratio ?? 0.8;
    const depthPx = (g.edge_depth_px || 45) * 0.4; // scale for preview

    if (g.edge === 'bottom') {
      const x = w * startRatio;
      const width = w * (endRatio - startRatio);
      const y = h - depthPx;
      ctx.fillRect(x, y, width, depthPx);
      ctx.strokeRect(x, y, width, depthPx);

      ctx.fillStyle = '#f5fff9';
      ctx.font = '12px Inter, sans-serif';
      ctx.fillText('▲ Swipe Up for OSK', w / 2, y + depthPx / 2 + 4);
    } else if (g.edge === 'top') {
      const x = w * startRatio;
      const width = w * (endRatio - startRatio);
      ctx.fillRect(x, 0, width, depthPx);
      ctx.strokeRect(x, 0, width, depthPx);
    }
  });
}
