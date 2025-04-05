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
    if typ == "int": return int(raw)
    if typ == "float": return float(raw)
    if typ == "bool": return raw.lower() in ["true", "1", "yes"]
    return str(raw)

def apply_runtime_setter(spec, value, mgr):
    if "real_time_setter" in spec:
        return spec["real_time_setter"](value, mgr)
    if "setter_name" in spec:
        setter_fn = current_app.config["SETTERS"].get(spec["setter_name"])
        if setter_fn:
            return setter_fn(value)
        raise RuntimeError(f"Setter '{spec['setter_name']}' not found.")


# @settings_bp.route('/settings', methods=['GET', 'POST'])
# def settings():
#     # Process settings here with form submission or any other logic
#     if request.method == 'POST':

#         # Update table refresh rate
#         if request.form['auto_refresh_table']:
#             current_app.config['AUTO_REFRESH_TABLE'] = tipify(request.form['auto_refresh_table'])*1000
#             current_app.config['LOGGER'].info(f'set auto refresh rate for table at {current_app.config["AUTO_REFRESH_TABLE"]/1000} s')

#         # Update Aggregator refresh rate
#         if request.form['aggregator_interval']:
#             aggregator_refresh_rate = tipify(request.form['aggregator_interval'])
#             try:
#                 current_app.config['SETTERS']['aggregator_refresh_rate'](aggregator_refresh_rate)
#                 current_app.config['LOGGER'].info(f'set Aggregator refresh rate at {aggregator_refresh_rate} s')
#             except:
#                 current_app.config['LOGGER'].warning(f'could not set Aggregator refresh rate')

#         # Toggle between 'static' and 'real-time' plot modes
#         if request.form.get('plot_mode'):
#             plot_mode = request.form['plot_mode']
#             if plot_mode in ['static', 'real-time']:
#                 current_app.config['PLOT_MODE'] = plot_mode
#                 current_app.config['LOGGER'].info(f'set plot mode to {plot_mode}')
#             else:
#                 current_app.config['LOGGER'].warning(f'invalid plot mode: {plot_mode}')

#         # ADD OTHER TOGGLES HERE

#         # Update settings
#         return render_template('settings.html', success=True)
#     return render_template('settings.html', success=False)
