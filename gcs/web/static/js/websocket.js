/**
 * WebSocket connection manager for Multi-Drone Dashboard.
 * Connects to /ws/telemetry, maintains telemetryState + per-drone heartbeat tracking.
 */

var telemetryState = {};
let ws = null;
let wsRetryCount = 0;
const MAX_RETRIES = 10;
const HEARTBEAT_TIMEOUT_SEC = 5;

// Per-drone last-seen timestamps for offline detection
var droneLastSeen = {};

// Per-drone local NED position {n, e, d} (meters). Derived from
// LOCAL_POSITION_NED (preferred) or computed from GLOBAL_POSITION_INT.
var droneNED = {};
// Per-drone NED reference origin {lat, lon, alt} captured on first valid fix.
var droneNEDOrigin = {};

// WGS84 equatorial radius (m), used for the flat-earth NED conversion.
const WGS84_RADIUS_M = 6378137.0;

/**
 * Connect to the telemetry WebSocket endpoint.
 */
function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const port = location.port || '8000';
    const wsUrl = `${protocol}//${location.hostname}:${port}/ws/telemetry`;

    updateWsStatus('reconnecting');

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('[WS] Connected to', wsUrl);
        wsRetryCount = 0;
        updateWsStatus('connected');
    };

    ws.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'telemetry') {
                telemetryState = payload;

                // Update per-drone last-seen timestamps
                const now = Date.now() / 1000;
                if (payload.drones) {
                    for (const sysid of Object.keys(payload.drones)) {
                        const drone = payload.drones[sysid];
                        if (drone.heartbeat && drone.heartbeat.mode !== 'N/A') {
                            droneLastSeen[sysid] = now;
                        }
                        // Update cached local NED position for this drone
                        updateDroneNED(sysid, drone);
                    }
                }

                // Dispatch to dashboard update
                if (typeof updateDashboard === 'function') {
                    updateDashboard();
                }
            }
        } catch (e) {
            console.error('[WS] Failed to parse message:', e);
        }
    };

    ws.onclose = () => {
        console.warn('[WS] Connection closed');
        updateWsStatus('disconnected');
        scheduleReconnect();
    };

    ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        updateWsStatus('disconnected');
    };
}

/**
 * Schedule a reconnection attempt with exponential backoff.
 */
function scheduleReconnect() {
    if (wsRetryCount >= MAX_RETRIES) {
        console.error('[WS] Max retries reached, giving up.');
        updateWsStatus('disconnected');
        return;
    }

    const delay = Math.min(5000 * Math.pow(2, wsRetryCount), 60000);
    wsRetryCount++;
    console.log(`[WS] Reconnecting in ${delay / 1000}s (attempt ${wsRetryCount}/${MAX_RETRIES})...`);
    updateWsStatus('reconnecting');

    setTimeout(() => {
        connectWebSocket();
    }, delay);
}

/**
 * Update the WS status indicator in the UI.
 */
function updateWsStatus(status) {
    const dot = document.getElementById('ws-dot');
    const text = document.getElementById('ws-text');
    if (!dot || !text) return;

    dot.className = 'status-dot';
    switch (status) {
        case 'connected':
            dot.classList.add('on');
            text.textContent = 'Connected';
            break;
        case 'disconnected':
            dot.classList.add('off');
            text.textContent = 'Disconnected';
            break;
        case 'reconnecting':
            dot.classList.add('off');
            text.textContent = `Reconnecting... (${wsRetryCount}/${MAX_RETRIES})`;
            break;
    }
}

/**
 * Check if a drone is considered online (has heartbeat within timeout).
 */
function isDroneOnline(sysid) {
    // Backend online flag takes priority when available.
    // When the backend explicitly marks a drone online, trust it.
    const drones = telemetryState.drones || {};
    const drone = drones[String(sysid)];
    if (drone && drone.online === true) return true;
    if (drone && drone.online === false) return false;
    // Fallback: WebSocket-side heartbeat timeout detection
    const lastSeen = droneLastSeen[String(sysid)] || 0;
    return (Date.now() / 1000 - lastSeen) < HEARTBEAT_TIMEOUT_SEC;
}

/**
 * Get all currently online drone IDs.
 */
function getOnlineDroneIds() {
    const drones = telemetryState.drones || {};
    return Object.keys(drones).filter(id => {
        const drone = drones[id];
        return drone && drone.heartbeat && drone.heartbeat.mode !== 'N/A';
    }).map(Number);
}

/**
 * Update the cached local NED position for a drone from the latest payload.
 *
 * Prefers an explicit LOCAL_POSITION_NED-derived `local_position` field
 * ({n, e, d} in meters). Falls back to computing local NED from the
 * GLOBAL_POSITION_INT-derived `gps` lat/lon/alt relative to a per-drone
 * reference origin captured on the first valid fix.
 */
function updateDroneNED(sysid, drone) {
    const key = String(sysid);

    // Offline drones have no meaningful position.
    if (!drone || drone.online === false) {
        droneNED[key] = null;
        return;
    }

    // 1) Prefer explicit LOCAL_POSITION_NED data when the backend provides it.
    const lp = drone.local_position;
    if (lp &&
        lp.n !== null && lp.n !== undefined &&
        lp.e !== null && lp.e !== undefined &&
        lp.d !== null && lp.d !== undefined) {
        droneNED[key] = { n: lp.n, e: lp.e, d: lp.d };
        return;
    }

    // 2) Otherwise derive local NED from GLOBAL_POSITION_INT (lat/lon/alt).
    const gps = drone.gps;
    if (!gps ||
        gps.lat === null || gps.lat === undefined ||
        gps.lon === null || gps.lon === undefined ||
        gps.alt === null || gps.alt === undefined) {
        return; // keep last known NED; no new valid position this frame
    }

    // Capture the reference origin on the first valid fix.
    if (!droneNEDOrigin[key]) {
        droneNEDOrigin[key] = { lat: gps.lat, lon: gps.lon, alt: gps.alt };
    }

    droneNED[key] = computeNED(gps.lat, gps.lon, gps.alt, droneNEDOrigin[key]);
}

/**
 * Convert a geodetic position to local NED (meters) relative to an origin
 * using a flat-earth (equirectangular) approximation. Accurate for the
 * short ranges relevant to RTK precision control.
 */
function computeNED(lat, lon, alt, origin) {
    const deg2rad = Math.PI / 180.0;
    const dLat = (lat - origin.lat) * deg2rad;
    const dLon = (lon - origin.lon) * deg2rad;
    const lat0 = origin.lat * deg2rad;

    const north = dLat * WGS84_RADIUS_M;
    const east = dLon * WGS84_RADIUS_M * Math.cos(lat0);
    const down = -(alt - origin.alt); // NED: down positive

    return { n: north, e: east, d: down };
}

/**
 * Get the cached local NED position {n, e, d} for a drone, or null.
 */
function getDroneNED(sysid) {
    return droneNED[String(sysid)] || null;
}

/**
 * Reset the NED reference origin for a drone so it re-zeroes at the current
 * position on the next valid fix. Useful when re-homing for RTK control.
 */
function resetDroneNEDOrigin(sysid) {
    delete droneNEDOrigin[String(sysid)];
    droneNED[String(sysid)] = null;
}

// Expose getters globally
window.getTelemetryState = () => telemetryState;
window.isDroneOnline = isDroneOnline;
window.getOnlineDroneIds = getOnlineDroneIds;
window.droneLastSeen = droneLastSeen;
window.getDroneNED = getDroneNED;
window.resetDroneNEDOrigin = resetDroneNEDOrigin;
window.droneNED = droneNED;

// Auto-connect when script loads
connectWebSocket();
