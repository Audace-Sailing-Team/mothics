from flask import Blueprint, render_template, jsonify, request, Response, current_app
from ..helpers import tipify
from .settings_registry import SETTINGS_REGISTRY


settings_bp = Blueprint("settings", __name__)

@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    system_manager = current_app.config["SYSTEM_MGR"]
    success_message = None
    error_message = None

    if request.method == "POST":
        for field, raw_value in request.form.items():
            if field not in SETTINGS_REGISTRY:
                continue  # Skip unknown fields

            spec = SETTINGS_REGISTRY[field]
            try:
                if spec.get("type") == "button":
                    apply_runtime_setter(spec, None, system_manager)
                    success_message = spec.get("log_success", "").format(value="")
                    continue

                value = parse_value(raw_value, spec["type"])
                if "validate" in spec and not spec["validate"](value):
                    raise ValueError(f"Validation failed for {field} = {value}")

                # Apply runtime effect
                apply_runtime_setter(spec, value, system_manager)

                success_message = spec.get("log_success", f"Updated {field} to {value}").format(value=value)

            except Exception as e:
                error_message = f"Error processing {field}: {e}"

    return render_template("settings.html",
                           success=success_message,
                           error=error_message,
                           registry=SETTINGS_REGISTRY)


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
            if not isinstance(parsed, list):
                raise ValueError("Expected list for taglist")
            return parsed
        except json.JSONDecodeError:
            # fallback: try CSV
            return [x.strip() for x in raw.split(",") if x.strip()]
    if typ == "kvtable":
        if isinstance(raw, dict):
            return raw  # already parsed
        try:
            return json.loads(raw)
        except Exception:
            raise ValueError("Invalid JSON for kvtable")
    if typ == "text":
        return str(raw)  # multiline textarea, no parsing
    return str(raw)  # fallback


def apply_runtime_setter(spec, value, mgr):
    if "real_time_setter" in spec:
        return spec["real_time_setter"](value, mgr)
    if "setter_name" in spec:
        setter_fn = current_app.config["SETTERS"].get(spec["setter_name"])
        if setter_fn:
            return setter_fn(value)
        raise RuntimeError(f"Setter '{spec['setter_name']}' not found.")
