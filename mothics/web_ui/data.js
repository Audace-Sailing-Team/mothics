// ===============================
//  API CLIENT PER MOTHICS
// ===============================

const API_BASE = "/api";

// Utility per chiamate GET
async function apiGet(path) {
    const res = await fetch(API_BASE + path);
    return res.json();
}

// Utility per chiamate POST
async function apiPost(path, body = {}) {
    const res = await fetch(API_BASE + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
    return res.json();
}

// ===============================
//  STATUS & MONITORING
// ===============================

export function getStatus() {
    return apiGet("/status");
}

export function getMonitor() {
    return apiGet("/monitor");
}

export function getCurrentData() {
    return apiGet("/data");
}

// ===============================
//  START / STOP / RESTART
// ===============================

export function startLive() {
    return apiPost("/start", { mode: "live" });
}

export function startReplay(trackFile) {
    return apiPost("/start", { mode: "replay", track: trackFile });
}

export function stopSystem() {
    return apiPost("/stop");
}

export function restartSystem(reloadConfig = false) {
    return apiPost("/restart", { reload_config: reloadConfig });
}

// ===============================
//  CONFIGURAZIONE
// ===============================

export function getConfig() {
    return apiGet("/config");
}

export function updateConfig(newConfig) {
    return apiPost("/config/update", newConfig);
}

export function saveConfig() {
    return apiPost("/config/save");
}

// ===============================
//  SALVATAGGIO TRACK
// ===============================

export function startSaving() {
    return apiPost("/save/start");
}

export function stopSaving() {
    return apiPost("/save/stop");
}

// ===============================
//  AGGREGATORE
// ===============================

export function setAggregatorInterval(interval) {
    return apiPost("/aggregator/interval", { interval });
}

// ===============================
//  DATABASE / TRACKS
// ===============================

export function listTracks() {
    return apiGet("/database/list");
}

export function selectTrack(index) {
    return apiPost("/database/select", { index });
}

// ===============================
//  LOG
// ===============================

export function getLog() {
    return apiGet("/log");
}

export function clearLog() {
    return apiPost("/log/clear");
}


export function startStream(callback) {
    const evt = new EventSource("/api/stream");

    evt.onmessage = (msg) => {
        try {
            const data = JSON.parse(msg.data);
            callback(data);
        } catch (e) {
            console.error("Errore stream:", e);
        }
    };

    evt.onerror = () => {
        console.error("Stream interrotto");
    };
}
