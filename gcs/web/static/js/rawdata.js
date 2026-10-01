/**
 * Raw data display for GCS Dashboard.
 * Shows telemetryState as formatted JSON in pre#raw-data-content.
 * Only updates when the Raw Data tab is active.
 */

let rawDataScrollPos = 0;

/**
 * Check if the Raw Data tab is currently active.
 */
function isRawDataTabActive() {
    const rawTab = document.getElementById('tab-raw');
    return rawTab ? rawTab.classList.contains('active') : false;
}

/**
 * Update the raw data display.
 * Called every second from the websocket update chain.
 */
function updateRawData() {
    if (!isRawDataTabActive()) return;

    const pre = document.getElementById('raw-data-content');
    if (!pre) return;

    const sysid = getSelectedSystemId();
    if (sysid === null) {
        pre.textContent = 'No drone selected';
        return;
    }

    const drones = telemetryState.drones || {};
    const drone = drones[String(sysid)];
    if (!drone) {
        pre.textContent = `No data for drone ${sysid}`;
        return;
    }

    // Save scroll position
    rawDataScrollPos = pre.scrollTop;

    // Build formatted output
    let output = `=== System ID: ${sysid} === Timestamp: ${telemetryState.timestamp || 'N/A'} ===\n\n`;

    // Connection status
    if (telemetryState.connection) {
        output += '[CONNECTION]\n';
        output += JSON.stringify(telemetryState.connection, null, 2);
        output += '\n\n';
    }

    // Drone data
    for (const [key, value] of Object.entries(drone)) {
        output += `[${key.toUpperCase()}]\n`;
        if (value && typeof value === 'object') {
            output += JSON.stringify(value, null, 2);
        } else {
            output += String(value);
        }
        output += '\n\n';
    }

    // RTK status
    if (telemetryState.rtk) {
        output += '[RTK]\n';
        output += JSON.stringify(telemetryState.rtk, null, 2);
        output += '\n';
    }

    pre.textContent = output;

    // Restore scroll position
    pre.scrollTop = rawDataScrollPos;
}
