"""
All of the settings shown in the WebApp (`bp_settings.py`) can be
defined and edited here.

Structure 
---------
The registry is based around a dictionary containing an entry for each
setting to be displayed. The entry structure is

    {
    "setting_name": {
        "type": "float",
        "validate": lambda v: v > 0,
        "setter_name": "aggregator_refresh_rate",
        "config_path": ("aggregator", "interval"),
        "log_success": "Value set to set to {value} seconds."
    }

with the following fields:
 - `type`: accepted type in the `WebApp` form
 - `validate`: input validation procedure, *e.g.* allowed values, min/max limits, ...
 - `setter_name`: name of the setter passed to the `WebApp` via the `WebApp.setters` dictionary
 - `config_path`: where the config can be found inside the configuration file
 - `log_success`: success message when form is submitted

An alternative approach relies on directly acting on `SystemManager`
methods, instead of defining and passing a specific setter for the
setting

    "setting_name": {
        "type": "float",
        "validate": lambda v: v > 0,
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('AUTO_REFRESH_TABLE', v * 1000),
        "config_path": ("webapp", "data_refresh"),
        "log_success": "Auto-refresh set to {value} s"
    }

A lambda function is defined, which takes the input form value and the
`SystemManager` instance as arguments.
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
