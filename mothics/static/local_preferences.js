const LOCAL_PREFS_KEY = "mothicsLocalPrefs";

export const LOCAL_SETTINGS_REGISTRY = {
  prefSpeedUnits: {
    type: "string",
    label: "Speed units",
    default: "km/h",
    choices: ["km/h", "knots", "mph", "m/s"]
  }
};

export function buildLocalPrefsForm(containerId) {
  const form = document.getElementById(containerId);
  if (!form) return;

  form.innerHTML = "";

  Object.entries(LOCAL_SETTINGS_REGISTRY).forEach(([key, cfg]) => {
    const wrapper = document.createElement("div");
    wrapper.className = "mb-3";

    const label = document.createElement("label");
    label.className = "form-label";
    label.htmlFor = key;
    label.textContent = cfg.label;
    wrapper.appendChild(label);

    let input;

    if (cfg.choices) {
      input = document.createElement("select");
      input.className = "form-select";
      input.id = key;
      cfg.choices.forEach(optVal => {
        const opt = document.createElement("option");
        opt.value = optVal;
        opt.textContent = optVal;
        input.appendChild(opt);
      });
    } else if (cfg.type === "boolean") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.className = "form-check-input";
      input.id = key;
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.className = "form-control";
      input.id = key;
    }

    wrapper.appendChild(input);
    form.appendChild(wrapper);
  });
}

export function loadLocalPrefsToForm() {
  const stored = JSON.parse(localStorage.getItem(LOCAL_PREFS_KEY) || "{}");

  Object.entries(LOCAL_SETTINGS_REGISTRY).forEach(([key, cfg]) => {
    const el = document.getElementById(key);
    const val = stored[key] !== undefined ? stored[key] : cfg.default;

    if (cfg.choices) el.value = val;
    else if (cfg.type === "boolean") el.checked = val;
    else el.value = val;
  });
}

export function saveLocalPrefsFromForm() {
  const result = {};
  Object.entries(LOCAL_SETTINGS_REGISTRY).forEach(([key, cfg]) => {
    const el = document.getElementById(key);
    if (!el) return;

    let val;
    if (cfg.choices) val = el.value;
    else if (cfg.type === "boolean") val = el.checked;
    else if (cfg.type === "int") val = parseInt(el.value);
    else if (cfg.type === "float") val = parseFloat(el.value);
    else val = el.value;

    result[key] = val;
  });

  localStorage.setItem(LOCAL_PREFS_KEY, JSON.stringify(result));
  alert("Preferences saved.");
}

export function getLocalPrefs() {
  const stored = JSON.parse(localStorage.getItem(LOCAL_PREFS_KEY) || "{}");
  const complete = {};
  for (const [key, cfg] of Object.entries(LOCAL_SETTINGS_REGISTRY)) {
    complete[key] = (key in stored) ? stored[key] : cfg.default;
  }
  return complete;
}

// Converts from km/h to desired unit
export function convertSpeedFromKmh(kmh, unit) {
  switch (unit) {
    case "knots": return kmh * 0.539957;
    case "mph": return kmh * 0.621371;
    case "m/s": return kmh / 3.6;
    default: return kmh; // km/h
  }
}
