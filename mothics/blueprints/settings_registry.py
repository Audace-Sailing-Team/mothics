"""
All of the settings shown in the WebApp (`bp_settings.py`) are
defined and configured here in a centralized registry.

Structure
---------
The registry is a dictionary, where each key is the name of a setting
and each value is a dictionary containing metadata and logic for how
to handle that setting in the UI and backend.

Example entry:

    "setting_name": {
        "type": "float",
        "tab": "Webapp",
        "label": "User-friendly label for the field",
        "placeholder": "Optional hint text",
        "validate": lambda v: v > 0,
        "choices": ["option1", "option2"],
        "setter_name": "some_runtime_setter",
        "config_path": ("section", "subkey"),
        "log_success": "Setting updated to {value}."
    }

Field descriptions:

 - `type`: type expected from user input; one of "string", "float", "int", "bool"
 - `tab`: tab name shown in the UI where the field will appear
 - `label`: human-readable label shown above the form input
 - `placeholder`: optional string shown as a hint inside the input box
 - `validate`: optional validation function applied after parsing
 - `choices`: optional list of values for select dropdown inputs
 - `setter_name`: name of a callable in `current_app.config['SETTERS']` for real-time updates
 - `real_time_setter`: alternatively, a direct function `(value, system_manager) -> None` for complex updates
 - `config_path`: tuple describing where the value lives in the nested config
 - `log_success`: log or UI message on successful update, with `{value}` placeholder

Notes
-----
- Either `setter_name` or `real_time_setter` must be provided.
- If `choices` is present, the form renders a `<select>` instead of a text input.
- If a setting is missing any optional field, sensible defaults will be used in the UI.

"""

SETTINGS_REGISTRY = {
    # ========== Aggregator Settings ==========
    "aggregator_interval": {
        "type": "float",
        "tab": "Data aggregation",
        "label": "Aggregator refresh interval (s)",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "setter_name": "aggregator_refresh_rate",
        "config_path": ("aggregator", "interval"),
        "log_success": "Aggregator interval set to {value} seconds."
    },

    # ========== WebApp Settings ==========
    "auto_refresh_table": {
        "type": "float",
        "tab": "Webapp",
        "label": "Dashboard refresh interval",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('AUTO_REFRESH_TABLE', v * 1000),
        "config_path": ("webapp", "data_refresh"),
        "log_success": "Auto-refresh set to {value} s"
    },
    
    "plot_mode": {
        "type": "string",
        "tab": "Webapp",
        "label": "Current plot mode",
        "validate": lambda v: v in ["Static", "Real-time"],
        "choices": ["Static", "Real-time"],
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('PLOT_MODE', v),
        "config_path": ("webapp", "plot_mode"),
        "log_success": "Plot mode changed to {value}"
    }
}
