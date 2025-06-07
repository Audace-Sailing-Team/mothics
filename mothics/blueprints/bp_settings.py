from flask import Blueprint, render_template, jsonify, request, current_app
import json
from .settings_registry import SETTINGS_REGISTRY
from ..helpers import list_required_tiles, download_tiles

settings_bp = Blueprint("settings", __name__)

def lookup_config_value(path, cfg):
    ref = cfg
    for key in path:
        ref = ref.get(key, {})
    return ref if ref != {} else ""

def parse_value(raw, typ):
    if typ == "int":
        return int(raw)
    if typ == "float":
        return float(raw)
    if typ == "bool":
        return raw.lower() in ["true", "1", "yes"]
    if typ == "taglist":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [x.strip() for x in raw.split(",") if x.strip()]
    if typ == "kvtable":
        if isinstance(raw, dict):
            return raw
        return json.loads(raw)
    if typ == "text":
        return str(raw)
    return str(raw)

def apply_runtime_setter(spec, value, mgr):
    """
    1) Apply the live effect (real_time_setter or setter_name)
    2) Mirror the new value into current_app.config["CONFIG_DATA"]
    """
    # 1) Live effect
    if "real_time_setter" in spec:
        result = spec["real_time_setter"](value, mgr)
    else:
        setter_name = spec.get("setter_name")
        setter_fn = current_app.config["SETTERS"].get(setter_name)
        if not setter_fn:
            raise RuntimeError(f"Setter '{setter_name}' not found.")
        result = setter_fn(value)

    # 2) Persist into CONFIG_DATA
    cfg = current_app.config["CONFIG_DATA"]
    node = cfg
    for key in spec["config_path"][:-1]:
        node = node.setdefault(key, {})
    node[spec["config_path"][-1]] = value

    return result

@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    mgr = current_app.config["SYSTEM_MGR"]
    success_message = None
    error_message = None

    if request.method == "POST":
        for field, raw_value in request.form.items():
            if field not in SETTINGS_REGISTRY:
                continue

            spec = SETTINGS_REGISTRY[field]
            try:
                # Button‐type settings just fire and mirror (value is ignored)
                if spec.get("type") == "button":
                    apply_runtime_setter(spec, None, mgr)
                    success_message = spec.get("log_success", "").format(value="")
                    continue

                # Parse & validate
                value = parse_value(raw_value, spec["type"])
                if "validate" in spec and not spec["validate"](value):
                    raise ValueError(f"Validation failed for {field} = {value}")

                # Apply & persist
                apply_runtime_setter(spec, value, mgr)
                success_message = spec.get("log_success",
                                           f"Updated {field} to {value}").format(value=value)

            except Exception as e:
                error_message = f"Error processing {field}: {e}"

    # Always rebuild current values from CONFIG_DATA
    cfg_data = current_app.config["CONFIG_DATA"]
    current_vals = {
        k: lookup_config_value(field["config_path"], cfg_data)
        for k, field in SETTINGS_REGISTRY.items()
    }

    return render_template(
        "settings.html",
        success=success_message,
        error=error_message,
        current=current_vals,
        registry=SETTINGS_REGISTRY
    )
