/**
 * Flight Control & Selection handlers for GCS Dashboard.
 * Attaches click events to all command buttons.
 */

document.addEventListener('DOMContentLoaded', function() {

    // ===== Connect / Disconnect Backend (status bar buttons) =====
    const btnConnect = document.getElementById('btn-connect-status');
    const btnDisconnect = document.getElementById('btn-disconnect-status');

    if (btnConnect) {
        btnConnect.addEventListener('click', function() {
            var statusEl = document.getElementById('backend-status-text');
            if (statusEl) { statusEl.textContent = 'Connecting...'; statusEl.className = 'status-value status-neutral'; }
            fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'connected') {
                    if (statusEl) { statusEl.textContent = 'Connected'; statusEl.className = 'status-value status-ok'; }
                } else {
                    if (statusEl) { statusEl.textContent = 'Error: ' + (data.detail || 'unknown'); statusEl.className = 'status-value status-error'; }
                }
            })
            .catch(function(err) {
                if (statusEl) { statusEl.textContent = 'Error: ' + (err.message || err); statusEl.className = 'status-value status-error'; }
            });
        });
    }

    if (btnDisconnect) {
        btnDisconnect.addEventListener('click', function() {
            var statusEl = document.getElementById('backend-status-text');
            if (statusEl) { statusEl.textContent = 'Disconnecting...'; statusEl.className = 'status-value status-neutral'; }
            fetch('/api/disconnect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'disconnected') {
                    if (statusEl) { statusEl.textContent = 'Not connected'; statusEl.className = 'status-value status-neutral'; }
                } else {
                    if (statusEl) { statusEl.textContent = 'Error: ' + (data.detail || 'unknown'); statusEl.className = 'status-value status-error'; }
                }
            })
            .catch(function(err) {
                if (statusEl) { statusEl.textContent = 'Error: ' + (err.message || err); statusEl.className = 'status-value status-error'; }
            });
        });
    }

    // ===== Select All / Clear Selection (guarded: may not exist) =====
    var btnSelectAll = document.getElementById('btn-select-all');
    var btnClearSel = document.getElementById('btn-clear-selection');

    if (btnSelectAll) {
        btnSelectAll.addEventListener('click', function() {
            document.querySelectorAll('.drone-card').forEach(function(card) {
                card.classList.add('selected');
            });
            if (typeof updateDashboard === 'function') updateDashboard();
        });
    }

    if (btnClearSel) {
        btnClearSel.addEventListener('click', function() {
            document.querySelectorAll('.drone-card.selected').forEach(function(card) {
                card.classList.remove('selected');
            });
            if (typeof updateDashboard === 'function') updateDashboard();
        });
    }

    // ===== Arm =====
    var btnArm = document.getElementById('btn-arm');
    if (btnArm) {
        btnArm.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            fetch('/api/arm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1 })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Arm'); })
            .catch(function(err) { updateCmdAckError('Arm', err); });
        });
    }

    // ===== Disarm =====
    var btnDisarm = document.getElementById('btn-disarm');
    if (btnDisarm) {
        btnDisarm.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            fetch('/api/disarm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1 })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Disarm'); })
            .catch(function(err) { updateCmdAckError('Disarm', err); });
        });
    }

    // ===== Force Arm =====
    var btnForceArm = document.getElementById('btn-force-arm');
    if (btnForceArm) {
        btnForceArm.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            showConfirmModal({
                title: 'FORCE ARM',
                message: '\u26A0\uFE0F Force Arm は ARMING_CHECK 等の安全チェックを無効化します。\n屋内テスト専用です。\n対象: ' + ids.length + ' 機\n本当に続行しますか？',
                confirmText: 'FORCE ARM 実行',
                variant: 'danger',
                onConfirm: function() {
                    fetch('/api/force_arm', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ system_ids: ids, component_id: 1, confirmed: true })
                    })
                    .then(function(r) { return r.json(); })
                    .then(function(data) { updateCmdAck(data, 'Force Arm'); })
                    .catch(function(err) { updateCmdAckError('Force Arm', err); });
                }
            });
        });
    }

    // ===== Takeoff =====
    var btnTakeoff = document.getElementById('btn-takeoff');
    if (btnTakeoff) {
        btnTakeoff.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            var altInput = document.getElementById('takeoff-altitude');
            var altitude = altInput ? parseFloat(altInput.value) : 10.0;
            fetch('/api/takeoff', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1, altitude: altitude })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Takeoff'); })
            .catch(function(err) { updateCmdAckError('Takeoff', err); });
        });
    }

    // ===== Land =====
    var btnLand = document.getElementById('btn-land');
    if (btnLand) {
        btnLand.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            var rateInput = document.getElementById('land-descent-rate');
            var descent_rate = rateInput ? parseFloat(rateInput.value) : 1.5;
            fetch('/api/land', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1, descent_rate: descent_rate })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Land'); })
            .catch(function(err) { updateCmdAckError('Land', err); });
        });
    }

    // ===== Guided Position =====
    var btnGuidedPos = document.getElementById('btn-guided-position');
    if (btnGuidedPos) {
        btnGuidedPos.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            var north = parseFloat(document.getElementById('guided-north').value || 0);
            var east  = parseFloat(document.getElementById('guided-east').value || 0);
            var down  = parseFloat(document.getElementById('guided-down').value || 0);
            var yaw   = parseFloat(document.getElementById('guided-yaw').value || 0);
            fetch('/api/guided/position', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1, north: north, east: east, down: down, yaw: yaw })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Guided Position'); })
            .catch(function(err) { updateCmdAckError('Guided Position', err); });
        });
    }

    // ===== Guided Velocity =====
    var btnGuidedVel = document.getElementById('btn-guided-velocity');
    if (btnGuidedVel) {
        btnGuidedVel.addEventListener('click', function() {
            var ids = getSelectedSystemIds();
            if (ids.length === 0) { showToast('ドローンカードを1つ以上選択してください', 'warn'); return; }
            var vx  = parseFloat(document.getElementById('guided-vx').value || 0);
            var vy  = parseFloat(document.getElementById('guided-vy').value || 0);
            var vz  = parseFloat(document.getElementById('guided-vz').value || 0);
            var yaw = parseFloat(document.getElementById('guided-yaw-vel').value || 0);
            fetch('/api/guided/velocity', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, component_id: 1, vx: vx, vy: vy, vz: vz, yaw: yaw })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Guided Velocity'); })
            .catch(function(err) { updateCmdAckError('Guided Velocity', err); });
        });
    }

});

function updateCmdAck(data, label) {
    var status = data.status || 'unknown';
    var ok = (status === 'ok' || status === 'sent' || status === 'partial');
    var el = document.getElementById('cmd-ack');
    if (el) {
        el.textContent = label + ': ' + status;
        el.className = ok ? 'value status-ok' : 'value status-error';
        return;
    }
    // No dedicated status element in the layout: surface the command response
    // as a non-blocking toast (single source of truth for command feedback)
    // instead of leaving stray text in a corner of the page.
    if (typeof showToast === 'function') {
        showToast(label + ': ' + status, ok ? 'info' : 'error');
    }
}

function updateCmdAckError(label, err) {
    var msg = label + ': Error - ' + (err && (err.message || err));
    var el = document.getElementById('cmd-ack');
    if (el) {
        el.textContent = msg;
        el.className = 'value status-error';
        return;
    }
    if (typeof showToast === 'function') {
        showToast(msg, 'error');
    }
}

// ===== Broadcast / Per-Drone Control Functions =====

/**
 * Get selected drone system IDs from drone cards with .selected class.
 * Falls back to first online drone if nothing selected.
 */
function getSelectedSystemIds() {
    var ids = [];
    var cards = document.querySelectorAll('.drone-card.selected');
    cards.forEach(function(card) {
        var sid = card.getAttribute('data-system-id');
        if (sid) ids.push(parseInt(sid, 10));
    });
    if (ids.length > 0) return ids;

    // Fallback: first online drone
    if (typeof getOnlineDroneIds === 'function') {
        var online = getOnlineDroneIds();
        if (online.length > 0) return online;
    }
    return ids;
}

/**
 * Get all currently online drone IDs.
 */
function _getOnlineIds() {
    if (typeof getOnlineDroneIds === 'function') {
        return getOnlineDroneIds();
    }
    var drones = (typeof telemetryState !== 'undefined' && telemetryState.drones) ? telemetryState.drones : {};
    var ids = [];
    for (var key in drones) {
        if (drones.hasOwnProperty(key)) {
            ids.push(parseInt(key, 10));
        }
    }
    return ids;
}

/**
 * Show a custom confirm modal (replaces native confirm() for dangerous ops).
 * Provides a clearly visible safety dialog for broadcast ARM/DISARM.
 *
 * opts:
 *   title       {string}   modal heading
 *   message     {string}   body text (supports "\n" line breaks via CSS pre-line)
 *   confirmText {string}   label for the confirm button
 *   variant     {string}   'arm' (green btn / orange box) | 'disarm' (red btn / red box) | 'danger'
 *   onConfirm   {function} called only when the user confirms
 *
 * Falls back to the native confirm() if the modal markup is missing.
 */
function showConfirmModal(opts) {
    opts = opts || {};
    var overlay = document.getElementById('confirm-modal');

    if (!overlay) {
        if (window.confirm(opts.message || opts.title || 'Confirm?')) {
            if (typeof opts.onConfirm === 'function') opts.onConfirm();
        }
        return;
    }

    var box        = overlay.querySelector('.modal-box');
    var titleEl    = document.getElementById('confirm-modal-title');
    var messageEl  = document.getElementById('confirm-modal-message');
    var cancelBtn  = document.getElementById('confirm-modal-cancel');
    var confirmBtn = document.getElementById('confirm-modal-confirm');

    var variant = opts.variant || 'danger';
    var boxStyle = (variant === 'arm' || variant === 'warn') ? 'warn' : 'danger';
    if (box) box.className = 'modal-box ' + boxStyle;

    if (titleEl)   titleEl.textContent = opts.title || '確認';
    if (messageEl) messageEl.textContent = opts.message || '';
    if (confirmBtn) {
        confirmBtn.textContent = opts.confirmText || '実行';
        confirmBtn.className = 'modal-btn modal-btn-confirm ' + variant;
    }
    // A prior showAlertModal() call may have hidden the Cancel button. A
    // confirm dialog must always offer a Cancel, so restore it here.
    if (cancelBtn) {
        cancelBtn.style.display = '';
        cancelBtn.textContent = 'キャンセル';
    }

    function cleanup() {
        overlay.classList.remove('show');
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
        confirmBtn.removeEventListener('click', onConfirm);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlay);
        document.removeEventListener('keydown', onKey);
    }
    function onConfirm() {
        cleanup();
        if (typeof opts.onConfirm === 'function') opts.onConfirm();
    }
    function onCancel() { cleanup(); }
    function onOverlay(e) { if (e.target === overlay) cleanup(); }
    // Escape cancels. Enter is intentionally NOT bound to confirm (avoid
    // accidental execution of a dangerous broadcast command).
    function onKey(e) {
        if (e.key === 'Escape' || e.keyCode === 27) onCancel();
    }

    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlay);
    document.addEventListener('keydown', onKey);

    overlay.hidden = false;
    overlay.classList.add('show');
    overlay.setAttribute('aria-hidden', 'false');
    // Default focus on Cancel = safer default for a destructive action.
    if (cancelBtn) cancelBtn.focus();
}

/**
 * Show a single-button (OK only) notice modal for important errors / warnings
 * that must be acknowledged. Reuses the #confirm-modal markup, hiding the
 * Cancel button. Falls back to window.alert() if the markup is missing.
 *
 * opts:
 *   title   {string}   modal heading
 *   message {string}   body text ("\n" line breaks via CSS pre-line)
 *   okText  {string}   label for the single OK button (default "OK")
 *   variant {string}   'warn' (orange) | 'danger' (red). default 'warn'
 *   onClose {function} optional callback fired after dismissal
 */
function showAlertModal(opts) {
    opts = opts || {};
    var overlay = document.getElementById('confirm-modal');

    if (!overlay) {
        window.alert(opts.message || opts.title || '');
        if (typeof opts.onClose === 'function') opts.onClose();
        return;
    }

    var box        = overlay.querySelector('.modal-box');
    var titleEl    = document.getElementById('confirm-modal-title');
    var messageEl  = document.getElementById('confirm-modal-message');
    var cancelBtn  = document.getElementById('confirm-modal-cancel');
    var confirmBtn = document.getElementById('confirm-modal-confirm');

    var variant = (opts.variant === 'danger') ? 'danger' : 'warn';
    if (box) box.className = 'modal-box ' + variant;

    if (titleEl)   titleEl.textContent = opts.title || '通知';
    if (messageEl) messageEl.textContent = opts.message || '';

    // Single-button notice: hide Cancel, relabel Confirm to "OK".
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (confirmBtn) {
        confirmBtn.textContent = opts.okText || 'OK';
        confirmBtn.className = 'modal-btn modal-btn-confirm ' + variant;
    }

    function cleanup() {
        overlay.classList.remove('show');
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
        confirmBtn.removeEventListener('click', onClose);
        overlay.removeEventListener('click', onOverlay);
        document.removeEventListener('keydown', onKey);
        // Restore the Cancel button for subsequent confirm dialogs.
        if (cancelBtn) cancelBtn.style.display = '';
    }
    function onClose() {
        cleanup();
        if (typeof opts.onClose === 'function') opts.onClose();
    }
    function onOverlay(e) { if (e.target === overlay) onClose(); }
    // For a non-destructive notice, both Enter and Escape simply dismiss.
    function onKey(e) {
        if (e.key === 'Escape' || e.keyCode === 27 ||
            e.key === 'Enter'  || e.keyCode === 13) onClose();
    }

    confirmBtn.addEventListener('click', onClose);
    overlay.addEventListener('click', onOverlay);
    document.addEventListener('keydown', onKey);

    overlay.hidden = false;
    overlay.classList.add('show');
    overlay.setAttribute('aria-hidden', 'false');
    if (confirmBtn) confirmBtn.focus();
}

/**
 * Show a brief, non-blocking toast notification (top-center) for minor,
 * non-destructive notices such as selection prompts ("select a drone first")
 * or "no online drones". Important confirmations always use showConfirmModal();
 * important errors use showAlertModal(). The toast container is created lazily
 * and appended to <body>, so no markup changes to index.html are required.
 *
 * @param {string} message  Text to display.
 * @param {string} type     'info' | 'warn' | 'error' (controls accent color).
 */
function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.setAttribute('role', 'status');
    toast.textContent = message;
    container.appendChild(toast);

    // Trigger the enter transition on the next frame.
    requestAnimationFrame(function() { toast.classList.add('show'); });

    var hideTimer = setTimeout(function() { dismiss(); }, 3200);
    function dismiss() {
        clearTimeout(hideTimer);
        toast.classList.remove('show');
        // Remove from the DOM after the fade-out transition completes.
        setTimeout(function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 250);
    }
    // Allow click-to-dismiss.
    toast.addEventListener('click', dismiss);
}

/**
 * Broadcast Arm to all online drones.
 */
function broadcastArm() {
    var ids = _getOnlineIds();
    if (ids.length === 0) { showToast('オンラインのドローンがありません', 'warn'); return; }
    showConfirmModal({
        title: 'ARM ALL',
        message: '本当に全機アームしますか？\n対象: ' + ids.length + ' 機\n全機のプロペラが回転を開始します。',
        confirmText: 'ARM ALL 実行',
        variant: 'arm',
        onConfirm: function() {
            fetch('/api/arm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Broadcast Arm'); })
            .catch(function(err) { updateCmdAckError('Broadcast Arm', err); });
        }
    });
}

/**
 * Broadcast Disarm to all online drones.
 */
function broadcastDisarm() {
    var ids = _getOnlineIds();
    if (ids.length === 0) { showToast('オンラインのドローンがありません', 'warn'); return; }
    showConfirmModal({
        title: 'DISARM ALL',
        message: '本当に全機ディスアームしますか？\n対象: ' + ids.length + ' 機\n全機のプロペラが停止します。',
        confirmText: 'DISARM ALL 実行',
        variant: 'disarm',
        onConfirm: function() {
            fetch('/api/disarm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Broadcast Disarm'); })
            .catch(function(err) { updateCmdAckError('Broadcast Disarm', err); });
        }
    });
}

/**
 * Broadcast Takeoff to all online drones.
 */
function broadcastTakeoff() {
    var ids = _getOnlineIds();
    if (ids.length === 0) { showToast('オンラインのドローンがありません', 'warn'); return; }
    var altInput = document.getElementById('takeoff-all-alt');
    var altitude = altInput ? parseFloat(altInput.value) : 10.0;
    showConfirmModal({
        title: 'TAKEOFF ALL',
        message: '全機を離陸させますか？\n対象: ' + ids.length + ' 機\n目標高度: ' + altitude + ' m',
        confirmText: 'TAKEOFF ALL 実行',
        variant: 'warn',
        onConfirm: function() {
            fetch('/api/takeoff', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, altitude: altitude })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Broadcast Takeoff'); })
            .catch(function(err) { updateCmdAckError('Broadcast Takeoff', err); });
        }
    });
}

/**
 * Broadcast Land to all online drones.
 */
function broadcastLand() {
    var ids = _getOnlineIds();
    if (ids.length === 0) { showToast('オンラインのドローンがありません', 'warn'); return; }
    showConfirmModal({
        title: 'LAND ALL',
        message: '全機を着陸させますか？\n対象: ' + ids.length + ' 機',
        confirmText: 'LAND ALL 実行',
        variant: 'warn',
        onConfirm: function() {
            fetch('/api/land', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: ids, descent_rate: 1.5 })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Broadcast Land'); })
            .catch(function(err) { updateCmdAckError('Broadcast Land', err); });
        }
    });
}

/**
 * Stop (Land immediately) a single drone by system ID.
 */
function stopDrone(sysid) {
    showConfirmModal({
        title: 'STOP Drone ' + sysid,
        message: 'Drone ' + sysid + ' を直ちに着陸させますか？\n(緊急着陸)',
        confirmText: 'STOP 実行',
        variant: 'danger',
        onConfirm: function() {
            fetch('/api/land', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: [sysid] })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Stop Drone-' + sysid); })
            .catch(function(err) { updateCmdAckError('Stop Drone-' + sysid, err); });
        }
    });
}

/**
 * Force Arm a single drone (double confirm for safety).
 */
/**
 * Set flight mode for a single drone via dropdown.
 */
function changeMode(sysid, mode) {
    if (!mode) return;
    fetch('/api/set_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_id: sysid, mode: mode })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) { updateCmdAck(data, 'Mode ' + mode); })
    .catch(function(err) { updateCmdAckError('Mode ' + mode, err); });
}

function forceArmDrone(sysid) {
    showConfirmModal({
        title: 'FORCE ARM Drone ' + sysid,
        message: '\u26A0\uFE0F Drone ' + sysid + ' を Force Arm します。\nARMING_CHECK 等の安全チェックを無効化します。\n屋内テスト専用です。\n本当に続行しますか？',
        confirmText: 'FORCE ARM 実行',
        variant: 'danger',
        onConfirm: function() {
            fetch('/api/force_arm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: [sysid], confirmed: true })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Force Arm Drone-' + sysid); })
            .catch(function(err) { updateCmdAckError('Force Arm Drone-' + sysid, err); });
        }
    });
}

// ==========================================================================
// RTK Precision Control (per-drone): Heading + Distance guided move, and RTL
// ==========================================================================

/**
 * Store a per-drone RTK control input value so it survives the periodic
 * full card re-render (see dashboard.js renderDroneCard / rtkControlValues).
 *
 * @param {number} sysid  Target drone system id.
 * @param {string} field  'heading' or 'distance'.
 * @param {string} value  Raw input value (kept as string).
 */
function setRtkValue(sysid, field, value) {
    if (!window.rtkControlValues) window.rtkControlValues = {};
    if (!window.rtkControlValues[sysid]) window.rtkControlValues[sysid] = {};
    window.rtkControlValues[sysid][field] = value;
}

/**
 * Read the Heading/Distance inputs from a drone card and dispatch a guided
 * position move. Wired to the per-card "Go" button.
 *
 * @param {number} sysid  Target drone system id.
 */
function sendGuidedPositionFromInputs(sysid) {
    var card = document.querySelector('.drone-card[data-system-id="' + sysid + '"]');
    var hEl = card ? card.querySelector('.rtk-heading-input') : null;
    var dEl = card ? card.querySelector('.rtk-distance-input') : null;
    var heading = hEl ? parseFloat(hEl.value) : NaN;
    var distance = dEl ? parseFloat(dEl.value) : NaN;
    sendGuidedPosition(sysid, heading, distance);
}

/**
 * Compute a local-NED target from a compass Heading (deg) and Distance (m)
 * relative to the drone's current NED position, then send it as a GUIDED
 * position target via POST /api/guided/position.
 *
 * Heading convention: 0deg = North, 90deg = East (clockwise).
 *   dNorth = distance * cos(heading)
 *   dEast  = distance * sin(heading)
 * Altitude (Down) is held at the current value so the move is horizontal.
 *
 * @param {number} systemId  Target drone system id.
 * @param {number} heading   Compass heading in degrees (0-360).
 * @param {number} distance  Travel distance in meters (> 0).
 */
function sendGuidedPosition(systemId, heading, distance) {
    if (isNaN(heading) || heading < 0 || heading > 360) {
        showAlertModal({
            title: '入力エラー',
            message: 'Heading（方位）は 0〜360 度の数値で入力してください。',
            variant: 'warn'
        });
        return;
    }
    if (isNaN(distance) || distance <= 0) {
        showAlertModal({
            title: '入力エラー',
            message: 'Distance（距離）は正の数（メートル）で入力してください。',
            variant: 'warn'
        });
        return;
    }

    var headingRad = heading * Math.PI / 180.0;
    var dNorth = distance * Math.cos(headingRad);
    var dEast = distance * Math.sin(headingRad);

    // Current local NED (from GLOBAL_POSITION_INT / LOCAL_POSITION_NED).
    var ned = (typeof getDroneNED === 'function') ? getDroneNED(systemId) : null;

    var north, east, down;
    if (ned) {
        north = ned.n + dNorth;
        east = ned.e + dEast;
        down = ned.d;            // hold current altitude
    } else {
        // No local NED available yet: treat heading/distance as an offset from
        // the local origin and hold a conservative default altitude.
        north = dNorth;
        east = dEast;
        down = -5.0;
    }

    // Heading (0-360) -> yaw (-180..180) so the vehicle faces its travel
    // direction (matches /api/guided/position yaw validation range).
    var yaw = heading > 180 ? heading - 360 : heading;

    showConfirmModal({
        title: 'GUIDED 移動 Drone ' + systemId,
        message: 'Drone ' + systemId + ' を ' + distance.toFixed(1) + ' m / 方位 ' +
                 heading.toFixed(0) + '\u00B0 に移動させますか？\n' +
                 '目標 NED  N=' + north.toFixed(2) + '  E=' + east.toFixed(2) +
                 '  D=' + down.toFixed(2),
        confirmText: '移動 実行',
        variant: 'warn',
        onConfirm: function() {
            fetch('/api/guided/position', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    system_ids: [systemId], component_id: 1,
                    north: north, east: east, down: down, yaw: yaw
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'Guided Pos Drone-' + systemId); })
            .catch(function(err) { updateCmdAckError('Guided Pos Drone-' + systemId, err); });
        }
    });
}

/**
 * Send a Return-To-Launch (RTL) command to a single drone via POST /api/rtl.
 *
 * @param {number} systemId  Target drone system id.
 */
function sendRTL(systemId) {
    showConfirmModal({
        title: 'RTL Drone ' + systemId,
        message: 'Drone ' + systemId + ' を RTL（Return to Launch / 自動帰還）させますか？',
        confirmText: 'RTL 実行',
        variant: 'warn',
        onConfirm: function() {
            fetch('/api/rtl', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_ids: [systemId], component_id: 1 })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { updateCmdAck(data, 'RTL Drone-' + systemId); })
            .catch(function(err) { updateCmdAckError('RTL Drone-' + systemId, err); });
        }
    });
}
