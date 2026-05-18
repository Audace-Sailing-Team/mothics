import {
  getStatus,
  getMonitor,
  getCurrentData,
  startLive,
  startReplay,
  stopSystem,
  restartSystem,
  getConfig,
  updateConfig,
  saveConfig,
  startSaving,
  stopSaving,
  setAggregatorInterval,
  listTracks,
  selectTrack,
  getLog,
  clearLog
} from "./data.js";

// Get DOM elements
const statusBox = document.getElementById("statusBox");
const controlResult = document.getElementById("controlResult");
const configBox = document.getElementById("configBox");
const tracksBox = document.getElementById("tracksBox");
const logBox = document.getElementById("logBox");

// ===============================
// STATUS
// ===============================

function setStatusCell(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  
  el.textContent = value;
  el.classList.remove("status-ok", "status-bad");

  if (value === "running" || value === "active" || value === "live" || value === "served (static)") {
    el.classList.add("status-ok");
  } else {
    el.classList.add("status-bad");
  }
}

document.getElementById("btnRefreshStatus").onclick = async () => {
  try {
    const status = await getStatus();

    setStatusCell("st_mode", status.mode);
    setStatusCell("st_comm", status.communicator);
    setStatusCell("st_aggr", status.aggregator);
    setStatusCell("st_web", status.webapp);
    setStatusCell("st_track", status.track);
    setStatusCell("st_db", status.database);

  } catch (e) {
    console.error("Errore stato:", e);
  }
};


// ===============================
// CONTROL
// ===============================

document.getElementById("btnStartLive").onclick = async () => {
  try {
    const res = await startLive();
    controlResult.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    controlResult.textContent = "Errore: " + e.message;
  }
};

document.getElementById("btnStartReplay").onclick = async () => {
  try {
    // Per default usiamo track index 0
    const res = await startReplay("0");
    controlResult.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    controlResult.textContent = "Errore: " + e.message;
  }
};

document.getElementById("btnStop").onclick = async () => {
  try {
    const res = await stopSystem();
    controlResult.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    controlResult.textContent = "Errore: " + e.message;
  }
};

document.getElementById("btnRestart").onclick = async () => {
  try {
    const res = await restartSystem(false);
    controlResult.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    controlResult.textContent = "Errore: " + e.message;
  }
};

// ===============================
// CONFIG
// ===============================

document.getElementById("btnLoadConfig").onclick = async () => {
  try {
    const cfg = await getConfig();
    const rows = diffConfig(cfg.merged, cfg.defaults, cfg.overrides);
    renderConfigTable(rows);
  } catch (e) {
    alert("Errore caricamento config: " + e.message);
  }
};


document.getElementById("btnSaveConfig").onclick = async () => {
  try {
    const res = await saveConfig();
    alert("Config salvata: " + JSON.stringify(res));
  } catch (e) {
    alert("Errore nel salvataggio: " + e.message);
  }
};

// ===============================
// TRACKS
// ===============================

document.getElementById("btnListTracks").onclick = async () => {
  try {
    const res = await listTracks();
    tracksBox.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    tracksBox.textContent = "Errore: " + e.message;
  }
};

// ===============================
// LOG
// ===============================

document.getElementById("btnLoadLog").onclick = async () => {
  try {
    const res = await getLog();
    logBox.textContent = res.log || "(File di log vuoto)";
  } catch (e) {
    logBox.textContent = "Errore nel caricamento del log: " + e.message;
  }
};

document.getElementById("btnClearLog").onclick = async () => {
  try {
    const res = await clearLog();
    if (res.status === "log cleared") {
      logBox.textContent = "(Log cancellato)";
      alert("Log cancellato con successo");
    } else if (res.error) {
      alert("Errore: " + res.error);
    }
  } catch (e) {
    alert("Errore nella cancellazione del log: " + e.message);
  }
};

// Auto-refresh status on page load
window.addEventListener("load", async () => {
  const status = await getStatus();
  statusBox.textContent = JSON.stringify(status, null, 2);
});


function flattenConfig(obj, prefix = "") {
  let out = {};

  if (Array.isArray(obj)) {
    obj.forEach((item, index) => {
      const path = `${prefix}[${index}]`;
      if (typeof item === "object" && item !== null) {
        Object.assign(out, flattenConfig(item, path));
      } else {
        out[path] = item;
      }
    });
    return out;
  }

  if (typeof obj === "object" && obj !== null) {
    for (const [key, value] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (typeof value === "object" && value !== null) {
        Object.assign(out, flattenConfig(value, path));
      } else {
        out[path] = value;
      }
    }
    return out;
  }

  out[prefix] = obj;
  return out;
}

function unflattenConfig(flat) {
  const out = {};

  for (const [flatKey, value] of Object.entries(flat)) {
    const parts = flatKey.split(".");
    let ref = out;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];

      // Caso: array tipo i2c[0]
      const arrayMatch = part.match(/(.+)\[(\d +) \]/);

      if (arrayMatch) {
        const name = arrayMatch[1];
        const index = parseInt(arrayMatch[2]);

        if (!ref[name]) ref[name] = [];
        if (!ref[name][index]) ref[name][index] = {};

        if (i === parts.length - 1) {
          ref[name][index] = value;
        } else {
          ref = ref[name][index];
        }
        continue;
      }

      // Caso: chiave normale
      if (i === parts.length - 1) {
        ref[part] = value;
      } else {
        if (!ref[part]) ref[part] = {};
        ref = ref[part];
      }
    }
  }

  return out;
}


function diffConfig(merged, defaults, overrides) {
  const flatMerged = flattenConfig(merged);
  const flatDefaults = flattenConfig(defaults);
  const flatOverrides = flattenConfig(overrides);

  const keys = new Set([
    ...Object.keys(flatMerged),
    ...Object.keys(flatDefaults),
    ...Object.keys(flatOverrides)
  ]);

  const rows = [];

  for (const key of keys) {
    rows.push({
      key,
      merged: flatMerged[key],
      default: flatDefaults[key],
      override: flatOverrides[key],
      isOverride: key in flatOverrides,
      isDefault: flatMerged[key] === flatDefaults[key]
    });
  }

  return rows;
}


function renderConfigTable(rows) {
  const tbody = document.getElementById("configTableBody");
  tbody.innerHTML = "";

  for (const row of rows) {
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>${row.key}</td>
      <td>${row.merged}</td>
      <td>${row.default !== undefined ? row.default : "-"}</td>
      <td>${row.override !== undefined ? row.override : "-"}</td>
      <td>
        ${
          row.isOverride
            ? `<input data-key="${row.key}" value="${row.override}">`
            : `<span style="color:#888">default</span>`
        }
      </td>
    `;

    tbody.appendChild(tr);
  }
}


document.getElementById("btnSaveConfig").onclick = async () => {
  try {
    const inputs = document.querySelectorAll("input[data-key]");
    const flat = {};

    inputs.forEach(inp => {
      flat[inp.dataset.key] = inp.value;
    });

    const overrides = unflattenConfig(flat);

    await updateConfig(overrides);
    await saveConfig();

    alert("Configurazione salvata!");
  } catch (e) {
    alert("Errore nel salvataggio: " + e.message);
  }
};
