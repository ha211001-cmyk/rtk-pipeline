/**
 * Multi-Drone Dashboard - Card rendering, alert bar, RTK status, status updates.
 * Called from websocket.js onmessage every ~1 second.
 */

const MAX_SLOTS = 4;

/**
 * Per-drone RTK precision-control input values (Heading / Distance).
 * Persisted across the ~1 s full card re-render so typed values are not lost.
 * Keyed by system id: { <sysid>: { heading: '<deg>', distance: '<m>' } }.
 */
window.rtkControlValues = window.rtkControlValues || {};

/**
 * Escape HTML special characters to prevent XSS.
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Main update function - called from websocket onmessage.
 */
function updateDashboard() {
    const conn = telemetryState.connection || null;
    const drones = telemetryState.drones || {};
    const rtk = telemetryState.rtk || null;

    updateBackendStatus(conn);
    updateAlertBar(drones, conn);
    renderAllCards(drones, conn);
    updateRtkStatus(drones, rtk);
    updateAllNominal(drones, conn);
    updateConnectionUiState(conn);

    // Also update graph and raw data panels
    if (typeof updateGraphs === 'function') updateGraphs();
    if (typeof updateRawData === 'function') updateRawData();
}

/**
 * Update backend status text in status bar.
 */
function updateBackendStatus(conn) {
    const el = document.getElementById('backend-status-text');
    if (!el) return;

    if (!conn) {
        el.textContent = 'Not connected';
        el.className = 'status-value status-warn';
    } else if (conn.is_connected) {
        el.textContent = 'Connected';
        el.className = 'status-value status-ok';
    } else {
        el.textContent = 'Disconnected';
        el.className = 'status-value status-error';
    }
}
/**
 * Toggle overall UI state based on backend connection status.
 *
 * When the backend is NOT connected:
 *   - greys out + locks the broadcast panel (via the `disconnected` body class
 *     which CSS turns into opacity:0.4 + pointer-events:none)
 *   - pulses the status-bar Connect button to guide the operator
 *   - explicitly disables every broadcast control and per-drone card button
 *
 * When the backend IS connected the greyout and pulse are removed and the
 * broadcast controls are re-enabled (per-drone card buttons keep their own
 * online/armed-based disabled state from renderDroneCard()).
 */
function updateConnectionUiState(conn) {
    const backendOnline = !!(conn && conn.is_connected);

    // Body-level class drives `.disconnected .broadcast-panel` greyout in CSS.
    document.body.classList.toggle('disconnected', !backendOnline);

    // Pulse the Connect button while disconnected to strengthen the CTA.
    const connectBtn = document.getElementById('btn-connect-status');
    if (connectBtn) connectBtn.classList.toggle('pulse', !backendOnline);

    // Explicitly disable broadcast panel controls (pointer-events also blocks
    // clicks, but `disabled` also prevents keyboard focus / form submission).
    const panel = document.getElementById('broadcast-panel');
    if (panel) {
        panel.querySelectorAll('button, input, select').forEach(function(el) {
            el.disabled = !backendOnline;
        });
    }

    // When offline, force-disable any per-drone card operation buttons that
    // may still be present so they cannot be triggered.
    if (!backendOnline) {
        document
            .querySelectorAll('.drone-card .btn-stop, .drone-card .btn-force-arm-sm, .drone-card .mode-select')
            .forEach(function(el) { el.disabled = true; });
    }
}



/**
 * Update "All Systems Nominal" display and alert bar.
 */
function updateAllNominal(drones, conn) {
    const el = document.getElementById('all-nominal-text');
    if (!el) return;

    const backendOk = conn && conn.is_connected;
    if (!backendOk) {
        el.textContent = '';
        return;
    }

    // Count online drones
    let onlineCount = 0;
    for (const sysid of Object.keys(drones)) {
        if (isDroneOnline(parseInt(sysid))) onlineCount++;
    }
    el.textContent = onlineCount + ' drone(s) online';
}

/**
 * Update alert bar with aggregated warnings.
 */
function updateAlertBar(drones, conn) {
    const bar = document.getElementById('alert-bar');
    const icon = document.getElementById('alert-icon');
    const text = document.getElementById('alert-text');
    if (!bar || !icon || !text) return;

    // Backend not connected
    if (!conn || !conn.is_connected) {
        bar.className = 'alert-bar alert-warn';
        icon.textContent = '\u26A0';
        text.textContent = 'Backend offline';
        return;
    }

    const alerts = [];

    for (const sysid of Object.keys(drones)) {
        const drone = drones[sysid];
        const online = isDroneOnline(parseInt(sysid));
        const hb = drone.heartbeat;
        const bat = drone.battery;
        const gps = drone.gps;
        const cmd = drone.command_state;

        if (!online || !hb || hb.mode === 'N/A') {
            alerts.push({ level: 'critical', msg: 'Drone-' + sysid + ' NO SIGNAL' });
            continue;
        }

        if (bat && bat.remaining !== null && bat.remaining < 25) {
            alerts.push({ level: 'warning', msg: 'Drone-' + sysid + ' Battery ' + bat.remaining + '%' });
        }

        if (gps && gps.fix_type >= 0 && gps.fix_type <= 2) {
            alerts.push({ level: 'warning', msg: 'Drone-' + sysid + ' GPS ' + (gps.fix_name || 'NO_FIX') });
        }

        if (gps && gps.hdop !== null && gps.hdop >= 2.0) {
            alerts.push({ level: 'caution', msg: 'Drone-' + sysid + ' HDOP=' + gps.hdop.toFixed(1) });
        }

        if (cmd && cmd.last_ack && (cmd.last_ack.status === 'failed' || cmd.last_ack.status === 'timeout')) {
            alerts.push({ level: 'caution', msg: 'Drone-' + sysid + ' ' + cmd.last_ack.command + ' ' + cmd.last_ack.status });
        }
    }

    if (alerts.length === 0) {
        bar.className = 'alert-bar alert-ok';
        icon.textContent = '\u2713';
        text.textContent = 'All Systems Nominal';
    } else {
        const hasCritical = alerts.some(function(a) { return a.level === 'critical'; });
        const hasWarning = alerts.some(function(a) { return a.level === 'warning'; });
        const level = hasCritical ? 'critical' : (hasWarning ? 'warn' : 'warn');
        bar.className = 'alert-bar alert-' + level;
        icon.textContent = hasCritical ? '\u26D4' : '\u26A0';
        text.textContent = alerts.map(function(a) { return a.msg; }).join(' | ');
    }
}

/**
 * Render all 4 drone cards into the grid.
 */
function renderAllCards(drones, conn) {
    const grid = document.getElementById('multi-drone-grid');
    if (!grid) return;

    // When a <select> dropdown or an input is focused (e.g. the user is
    // picking a flight mode or typing a Heading/Distance value), do a
    // lightweight text-only update instead of replacing innerHTML so the
    // open dropdown / typed value is preserved.
    if (grid.querySelector('.mode-select:focus') || grid.querySelector('input:focus')) {
        updateCardValuesOnly(drones, conn);
        return;
    }

    const backendOnline = conn && conn.is_connected;
    let html = '';

    for (let i = 1; i <= MAX_SLOTS; i++) {
        const sysidStr = String(i);
        const drone = drones[sysidStr] || null;
        if (!backendOnline) {
            html += renderPlaceholderCard(i);
        } else if (!drone) {
            html += renderEmptyCard(i);
        } else {
            html += renderDroneCard(i, drone);
        }
    }

    const selectedSysid = getSelectedSystemId();
    grid.innerHTML = html;
    if (selectedSysid !== null) {
        const card = grid.querySelector('.drone-card[data-system-id="' + selectedSysid + '"]');
        if (card) card.classList.add('selected');
    }
}

/**
 * Render a single drone card.
 */

/**
 * Lightweight text-only card update when <select> dropdown is open.
 * Avoids innerHTML replacement so the dropdown stays open.
 */
function updateCardValuesOnly(drones, conn) {
    const grid = document.getElementById('multi-drone-grid');
    if (!grid) return;

    for (let i = 1; i <= MAX_SLOTS; i++) {
        const card = grid.querySelector('.drone-card[data-system-id="' + i + '"]');
        const drone = drones ? drones[String(i)] : null;
        if (!card || !drone) continue;

        const online = drone.online !== undefined ? drone.online : isDroneOnline(i);
        const hb = drone.heartbeat || {};
        const bat = drone.battery || {};
        const gps = drone.gps || {};
        const armed = online && hb.armed;

        // Armed badge
        const badge = card.querySelector('.armed-badge-mini');
        if (badge) {
            if (!online) { badge.textContent = 'NO SIGNAL'; badge.className = 'armed-badge-mini offline'; }
            else if (armed) { badge.textContent = 'ARMED'; badge.className = 'armed-badge-mini armed'; }
            else { badge.textContent = 'DISARMED'; badge.className = 'armed-badge-mini disarmed'; }
        }

        // Mode
        const modeEl = card.querySelector('.mode-value');
        if (modeEl) modeEl.textContent = online ? (hb.mode || '--') : '--';

        // Battery
        const voltEl = card.querySelector('.battery-voltage');
        if (voltEl) voltEl.textContent = bat.voltage !== null ? bat.voltage.toFixed(1) + 'V' : '--.-V';
        const fillEl = card.querySelector('.battery-fill');
        if (fillEl) {
            const r = bat.remaining !== null ? bat.remaining : 0;
            const fc = r <= 25 ? 'red' : (r <= 50 ? 'yellow' : 'green');
            fillEl.className = 'battery-fill ' + fc;
            fillEl.style.width = r + '%';
        }
        const pctEl = card.querySelector('.battery-pct');
        if (pctEl) {
            const r = bat.remaining !== null ? bat.remaining : 0;
            pctEl.textContent = r + '%';
            pctEl.className = r < 25 ? 'battery-pct low' : 'battery-pct';
        }

        // GPS
        const fixEl = card.querySelector('.gps-fix-badge');
        if (fixEl && gps.fix_type >= 0) {
            let fc = 'fix-bad';
            if (gps.fix_type >= 5) fc = 'fix-ok';
            else if (gps.fix_type >= 3) fc = 'fix-warn';
            fixEl.className = 'gps-fix-badge ' + fc;
            fixEl.textContent = gps.fix_name || 'UNKNOWN';
        } else if (fixEl) {
            fixEl.className = 'gps-fix-badge fix-bad';
            fixEl.textContent = '--';
        }

        const altEl = card.querySelector('.gps-altitude');
        if (altEl) altEl.textContent = gps.alt !== null ? gps.alt.toFixed(1) + 'm' : '--';

        const supp = card.querySelectorAll('.gps-supplement span');
        if (supp.length >= 2) {
            const sats = gps.satellites || 0;
            supp[0].textContent = sats + ' sats';
            supp[0].className = sats === 0 ? 'gps-sats-low' : '';
            supp[1].textContent = 'HDOP ' + (gps.hdop !== null ? gps.hdop.toFixed(2) : '--');
        }

        // NED local position
        const ned = (typeof getDroneNED === 'function') ? getDroneNED(i) : null;
        const nedN = card.querySelector('.ned-n');
        const nedE = card.querySelector('.ned-e');
        const nedD = card.querySelector('.ned-d');
        if (nedN && nedE && nedD) {
            if (!online || !ned) {
                nedN.textContent = 'N: --';
                nedE.textContent = 'E: --';
                nedD.textContent = 'D: --';
            } else {
                nedN.textContent = 'N: ' + ned.n.toFixed(2) + 'm';
                nedE.textContent = 'E: ' + ned.e.toFixed(2) + 'm';
                nedD.textContent = 'D: ' + ned.d.toFixed(2) + 'm';
            }
        }

        // Connection dot
        const dot = card.querySelector('.conn-dot');
        if (dot) dot.className = 'conn-dot ' + (online ? 'on' : 'off');

        // STOP button
        const stopBtn = card.querySelector('.btn-stop');
        if (stopBtn) {
            stopBtn.disabled = !online || !armed;
            stopBtn.textContent = !online ? '--' : (armed ? 'STOP' : 'DISARMED');
        }

        // Force button
        const forceBtn = card.querySelector('.btn-force-arm-sm');
        if (forceBtn) forceBtn.disabled = !online;

        // RTK precision-control buttons (Go / RTL)
        const goBtn = card.querySelector('.btn-go');
        if (goBtn) goBtn.disabled = !online;
        const rtlBtn = card.querySelector('.btn-rtl');
        if (rtlBtn) rtlBtn.disabled = !online;

        // Card class
        var newClass = !online ? 'drone-card offline' : (armed ? 'drone-card armed' : 'drone-card');
        if (card.classList.contains('selected')) newClass += ' selected';
        if (card.className !== newClass) card.className = newClass;
    }
}
function renderDroneCard(sysid, drone) {
    const online = drone.online !== undefined ? drone.online : isDroneOnline(sysid);
    const hb = drone.heartbeat || {};
    const bat = drone.battery || {};
    const gps = drone.gps || {};

    const armed = online && hb.armed;
    const cardClass = !online ? 'drone-card offline' : (armed ? 'drone-card armed' : 'drone-card');
    const connDotClass = online ? 'on' : 'off';

    // Armed badge
    let armedBadgeClass, armedBadgeText;
    if (!online) {
        armedBadgeClass = 'offline';
        armedBadgeText = 'NO SIGNAL';
    } else if (armed) {
        armedBadgeClass = 'armed';
        armedBadgeText = 'ARMED';
    } else {
        armedBadgeClass = 'disarmed';
        armedBadgeText = 'DISARMED';
    }

    // Flight mode
    const modeText = online ? (hb.mode || '--') : '--';

    // Battery row
    let batteryHtml;
    if (!online || bat.voltage === null) {
        batteryHtml = '<div class="battery-row"><span class="battery-voltage">--.-V</span><div class="battery-gauge"><div class="battery-fill" style="width:0%"></div></div><span class="battery-pct">--</span></div>';
    } else {
        const voltage = bat.voltage.toFixed(1) + 'V';
        const remaining = bat.remaining !== null ? bat.remaining : 0;
        let fillClass = 'green';
        if (remaining <= 25) fillClass = 'red';
        else if (remaining <= 50) fillClass = 'yellow';
        const pctClass = remaining < 25 ? 'battery-pct low' : 'battery-pct';
        const pct = remaining + '%';
        batteryHtml = '<div class="battery-row">' +
            '<span class="battery-voltage">' + voltage + '</span>' +
            '<div class="battery-gauge"><div class="battery-fill ' + fillClass + '" style="width:' + remaining + '%"></div></div>' +
            '<span class="' + pctClass + '">' + pct + '</span></div>';
    }

    // GPS row
    let gpsHtml;
    if (!online || gps.fix_type < 0) {
        gpsHtml = '<div class="gps-row"><span class="gps-fix-badge fix-bad">--</span><span class="gps-altitude">--</span></div>' +
                  '<div class="gps-supplement"><span>0 sats</span><span>HDOP --</span></div>';
    } else {
        const fixName = gps.fix_name || 'UNKNOWN';
        let fixClass = 'fix-bad';
        if (gps.fix_type >= 5) fixClass = 'fix-ok';
        else if (gps.fix_type >= 3) fixClass = 'fix-warn';

        const alt = gps.alt !== null ? gps.alt.toFixed(1) + 'm' : '--';
        const sats = gps.satellites || 0;
        const satsClass = sats === 0 ? 'gps-sats-low' : '';
        const hdop = gps.hdop !== null ? gps.hdop.toFixed(2) : '--';

        gpsHtml = '<div class="gps-row">' +
            '<span class="gps-fix-badge ' + fixClass + '">' + fixName + '</span>' +
            '<span class="gps-altitude">' + alt + '</span></div>' +
            '<div class="gps-supplement">' +
            '<span class="' + satsClass + '">' + sats + ' sats</span>' +
            '<span>HDOP ' + hdop + '</span></div>';
    }

    // NED local position row (North / East / Down in meters)
    const ned = (typeof getDroneNED === 'function') ? getDroneNED(sysid) : null;
    let nedHtml;
    if (!online || !ned) {
        nedHtml = '<div class="ned-row">' +
            '<span class="ned-coord ned-n">N: --</span>' +
            '<span class="ned-coord ned-e">E: --</span>' +
            '<span class="ned-coord ned-d">D: --</span></div>';
    } else {
        nedHtml = '<div class="ned-row">' +
            '<span class="ned-coord ned-n">N: ' + ned.n.toFixed(2) + 'm</span>' +
            '<span class="ned-coord ned-e">E: ' + ned.e.toFixed(2) + 'm</span>' +
            '<span class="ned-coord ned-d">D: ' + ned.d.toFixed(2) + 'm</span></div>';
    }

    // Debug box: render STATUSTEXT (all available, scrollable, color-coded by severity)
    const statusTexts = drone.status_texts || [];
    let debugHtml = '<div class="debug-box">';
    if (statusTexts.length === 0) {
        debugHtml += '<div class="debug-msg info">No status messages</div></div>';
    } else {
        for (let i = 0; i < statusTexts.length; i++) {
            const st = statusTexts[i];
            const sev = st.severity;
            // Color: 0-2=red(error), 3-4=orange(warn), 5-7=green(info)
            let cssClass;
            if (sev <= 2) {
                cssClass = 'error';
            } else if (sev <= 4) {
                cssClass = 'warn';
            } else {
                cssClass = 'info';
            }
            debugHtml += '<div class="debug-msg ' + cssClass + '">' +
                escapeHtml(st.text) + '</div>';
        }
        debugHtml += '</div>';
    }

    // STOP + Force Arm buttons
    const stopDisabled = !online || !armed ? ' disabled' : '';
    const stopText = !online ? '--' : (armed ? 'STOP' : 'DISARMED');
    const forceDisabled = !online ? ' disabled' : '';

    // Mode selector dropdown
    var modeOptions = ['STABILIZE','ALT_HOLD','GUIDED','LOITER','RTL','LAND','AUTO'];
    var modeSelectHtml = '<select class="mode-select" onchange="changeMode(' + sysid + ', this.value)">';
    modeSelectHtml += '<option value="" disabled selected>Mode</option>';
    for (var mi = 0; mi < modeOptions.length; mi++) {
        modeSelectHtml += '<option value="' + modeOptions[mi] + '">' + modeOptions[mi] + '</option>';
    }
    modeSelectHtml += '</select>';

    const buttonsHtml = '<div class="card-buttons">' +
        '<button class="btn-stop" onclick="stopDrone(' + sysid + ')"' + stopDisabled + '>' + stopText + '</button>' +
        '<button class="btn-force-arm-sm" onclick="forceArmDrone(' + sysid + ')"' + forceDisabled + '>Force</button>' +
        modeSelectHtml +
        '</div>';

    // RTK precision-control row: Heading (deg) / Distance (m) / Go / RTL.
    // Typed values persist across re-renders via window.rtkControlValues.
    const stored = window.rtkControlValues[sysid] || {};
    const headingVal = (stored.heading !== undefined && stored.heading !== null) ? stored.heading : '0';
    const distanceVal = (stored.distance !== undefined && stored.distance !== null) ? stored.distance : '1';
    const rtkDisabled = !online ? ' disabled' : '';
    const rtkHtml = '<div class="rtk-control-row">' +
        '<label class="rtk-ctrl-label">Hdg' +
            '<input class="rtk-input rtk-heading-input" type="number" min="0" max="360" step="1" ' +
                'value="' + headingVal + '" title="Heading (deg, 0-360)" ' +
                'onclick="event.stopPropagation()" ' +
                'oninput="setRtkValue(' + sysid + ', \'heading\', this.value)"' + rtkDisabled + '></label>' +
        '<label class="rtk-ctrl-label">Dist' +
            '<input class="rtk-input rtk-distance-input" type="number" min="0" max="1000" step="0.5" ' +
                'value="' + distanceVal + '" title="Distance (m)" ' +
                'onclick="event.stopPropagation()" ' +
                'oninput="setRtkValue(' + sysid + ', \'distance\', this.value)"' + rtkDisabled + '></label>' +
        '<button class="btn-go" onclick="sendGuidedPositionFromInputs(' + sysid + ')"' + rtkDisabled + '>Go</button>' +
        '<button class="btn-rtl" onclick="sendRTL(' + sysid + ')"' + rtkDisabled + '>RTL</button>' +
        '</div>';

    return '<div class="' + cardClass + '" data-system-id="' + sysid + '" onclick="selectCard(event, ' + sysid + ')">' +
        '<div class="card-header">' +
            '<span class="drone-label">DRONE ' + sysid + '</span>' +
            '<span class="conn-dot ' + connDotClass + '"></span>' +
        '</div>' +
        '<div style="text-align:center;"><span class="armed-badge-mini ' + armedBadgeClass + '">' + armedBadgeText + '</span></div>' +
        '<div class="mode-value">' + modeText + '</div>' +
        batteryHtml +
        gpsHtml +
        nedHtml +
        debugHtml +
        rtkHtml +
        buttonsHtml +
        '</div>';
}

/**
 * Render an empty card for a drone slot that has never been seen.
 */
function renderEmptyCard(sysid) {
    return '<div class="drone-card placeholder">' +
        '<div class="card-header">' +
            '<span class="drone-label">DRONE ' + sysid + '</span>' +
            '<span class="conn-dot off"></span>' +
        '</div>' +
        '<div style="text-align:center;padding-top:40px;">No drone</div>' +
        '</div>';
}

/**
 * Render a placeholder card when backend is offline.
 */
function renderPlaceholderCard(sysid) {
    return '<div class="drone-card placeholder">' +
        '<div class="card-header">' +
            '<span class="drone-label">DRONE ' + sysid + '</span>' +
            '<span class="conn-dot off"></span>' +
        '</div>' +
        '<div style="text-align:center;padding-top:40px;">Backend offline</div>' +
        '</div>';
}

/**
 * Update the RTK Fix status badge in the header status bar.
 *
 * The badge color reflects the best RTK fix achieved across all online drones:
 *   - RTK_FIXED (fix_type 6) -> green  "RTK: Fixed"
 *   - RTK_FLOAT (fix_type 5) -> yellow "RTK: Float"
 *   - otherwise              -> red    "RTK: None"
 *
 * A secondary detail line shows the RTK base station (RtcmReader) statistics.
 *
 * @param {Object} drones - Map of system id -> drone telemetry.
 * @param {Object} rtk    - RTK base station (RtcmReader) statistics.
 */
function updateRtkStatus(drones, rtk) {
    const badge = document.getElementById('rtk-badge');
    const detail = document.getElementById('rtk-detail');
    if (!badge) return;

    // Fix type constants (MAVLink GPS_FIX_TYPE)
    const RTK_FLOAT = 5;
    const RTK_FIXED = 6;

    // Find the best RTK fix state across all online drones.
    let best = 0;                 // 0 = none, 5 = float, 6 = fixed
    const fixedDrones = [];
    const floatDrones = [];
    if (drones) {
        for (const sysid of Object.keys(drones)) {
            if (!isDroneOnline(parseInt(sysid, 10))) continue;
            const gps = drones[sysid].gps;
            if (!gps || typeof gps.fix_type !== 'number') continue;
            if (gps.fix_type === RTK_FIXED) {
                fixedDrones.push(sysid);
                if (best < RTK_FIXED) best = RTK_FIXED;
            } else if (gps.fix_type === RTK_FLOAT) {
                floatDrones.push(sysid);
                if (best < RTK_FLOAT) best = RTK_FLOAT;
            }
        }
    }

    // Update the badge label + color class.
    if (best === RTK_FIXED) {
        badge.textContent = 'RTK: Fixed';
        badge.className = 'rtk-badge rtk-fixed';
        badge.title = 'RTK Fixed on drone(s): ' + fixedDrones.join(', ');
    } else if (best === RTK_FLOAT) {
        badge.textContent = 'RTK: Float';
        badge.className = 'rtk-badge rtk-float';
        badge.title = 'RTK Float on drone(s): ' + floatDrones.join(', ');
    } else {
        badge.textContent = 'RTK: None';
        badge.className = 'rtk-badge rtk-none';
        badge.title = 'No drone has reached RTK Float/Fixed';
    }

    // Update the RTK base station (RTCM) detail line.
    if (detail) {
        if (!rtk) {
            detail.textContent = 'Base: N/A';
        } else {
            const baseState = rtk.enabled ? 'Connected' : 'Disabled';
            detail.textContent = 'Base: ' + baseState +
                ' \u00B7 Msgs: ' + (rtk.messages_received || 0) +
                ' \u00B7 Reconn: ' + (rtk.reconnects || 0);
        }
    }
}

// Initial render on page load.
//
// This MUST run on first load so the broadcast panel (LAND ALL etc.) starts in
// the locked / greyed-out "disconnected" state until a live backend connection
// arrives. We pass an explicit `{ is_connected: false }` so the intent is clear
// and `updateConnectionUiState()` adds the `disconnected` body class + disables
// every broadcast control from the very first paint.
//
// If the DOM has already finished parsing by the time this script runs (e.g. the
// script is loaded with defer/async or injected late), `DOMContentLoaded` will
// never fire again, so apply the initial state synchronously in that case.
function initDashboardUiState() {
    renderAllCards({}, null);
    updateConnectionUiState({ is_connected: false });
}

if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', initDashboardUiState);
} else {
    initDashboardUiState();
}

/**
 * Toggle selection of a drone card by clicking it.
 * Ctrl/Cmd+click for multi-select, plain click replaces selection.
 */
function selectCard(event, sysid) {
    // Don't toggle selection when interacting with a control inside the card
    // (button, number input, mode dropdown).
    var tag = event.target.tagName;
    if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'OPTION') return;

    const card = document.querySelector('.drone-card[data-system-id="' + sysid + '"]');
    if (!card) return;

    const multi = event.ctrlKey || event.metaKey;

    if (!multi) {
        // Deselect all, then select this one
        document.querySelectorAll('.drone-card.selected').forEach(function(c) {
            c.classList.remove('selected');
        });
    }

    card.classList.toggle('selected');
}

/**
 * Get the system ID of the first selected card, or the first online drone as fallback.
 */
function getSelectedSystemId() {
    const sel = document.querySelector('.drone-card.selected');
    if (sel) {
        const sid = sel.getAttribute('data-system-id');
        if (sid) return parseInt(sid, 10);
    }
    // Fallback: first online drone
    const onlineIds = typeof getOnlineDroneIds === 'function' ? getOnlineDroneIds() : [];
    if (onlineIds.length > 0) return onlineIds[0];
    // Last resort: first card
    const first = document.querySelector('.drone-card[data-system-id]');
    if (first) return parseInt(first.getAttribute('data-system-id'), 10);
    return null;
}

/**
 * Switch between Graph and Raw Data tabs.
 */
function switchTab(tabName) {
    // Update tab button active states
    document.querySelectorAll('#tab-bar button').forEach(function(btn) {
        btn.classList.remove('active');
    });
    const tabBtn = document.getElementById('tab-' + tabName);
    if (tabBtn) tabBtn.classList.add('active');

    // Show/hide panels
    const panelGraph = document.getElementById('panel-graph');
    const panelRaw = document.getElementById('panel-raw');
    const panelOps = document.getElementById('panel-ops');
    if (panelGraph) panelGraph.style.display = (tabName === 'graph') ? 'block' : 'none';
    if (panelRaw)   panelRaw.style.display   = (tabName === 'raw')   ? 'block' : 'none';
    if (panelOps)   panelOps.style.display   = (tabName === 'ops')   ? 'block' : 'none';

    // If switching to graph, ensure graphs are initialized
    if (tabName === 'graph' && typeof initGraphs === 'function') {
        initGraphs();
    }
}

// Expose globally
window.selectCard = selectCard;
window.getSelectedSystemId = getSelectedSystemId;
window.switchTab = switchTab;
window.updateConnectionUiState = updateConnectionUiState;
