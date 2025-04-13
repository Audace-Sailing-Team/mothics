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
    # ========= Aggregator =========
    "aggregator_interval": {
        "type": "float",
        "tab": "Aggregator",
        "label": "Aggregator refresh interval (s)",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "setter_name": "aggregator_refresh_rate",
        "config_path": ("aggregator", "interval"),
        "log_success": "Aggregator interval set to {value} seconds."
    },

    # ========= Webapp =========
    "auto_refresh_table": {
        "type": "float",
        "tab": "Webapp",
        "label": "Dashboard auto-refresh interval (s)",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('AUTO_REFRESH_TABLE', v * 1000),
        "config_path": ("webapp", "data_refresh"),
        "log_success": "Auto-refresh rate set to {value} s"
    },
    "plot_mode": {
        "type": "string",
        "tab": "Webapp",
        "label": "Plotting mode",
        "choices": ["static", "real-time"],
        "validate": lambda v: v in ["static", "real-time"],
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('PLOT_MODE', v),
        "config_path": ("webapp", "plot_mode"),
        "log_success": "Plot mode changed to {value}"
    },
    "timeout_offline": {
        "type": "int",
        "tab": "Webapp",
        "label": "Offline timeout (s)",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('TIMEOUT_OFFLINE', v),
        "config_path": ("webapp", "timeout_offline"),
        "log_success": "Offline timeout set to {value} s"
    },
    "timeout_noncomm": {
        "type": "int",
        "tab": "Webapp",
        "label": "Non-communication timeout (s)",
        "placeholder": "Enter value in seconds...",
        "validate": lambda v: v > 0,
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('TIMEOUT_NONCOMM', v),
        "config_path": ("webapp", "timeout_noncomm"),
        "log_success": "Non-communication timeout set to {value} s"
    },

    # ========= Track (GPS) =========
    "track_variable": {
        "type": "string",
        "tab": "GPS Track",
        "label": "Track color variable",
        "choices": ["speed", "cog", "altitude", "sats"],
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('TRACK_VARIABLE', v),
        "config_path": ("webapp", "gps", "track_variable"),
        "log_success": "Track variable set to {value}"
    },

    "gps_history_minutes": {
    "type": "int",
    "tab": "GPS Track",
    "label": "GPS track history window (minutes)",
    "placeholder": "e.g. 10",
    "validate": lambda v: v > 0,
    "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('GPS_HISTORY_MINUTES', v),
    "config_path": ("webapp", "gps_history_window"),
    "log_success": "Set GPS history window to {value} minutes."
    },

    # ========= Database =========
    "database_validation": {
        "type": "bool",
        "tab": "Database",
        "label": "Enable track schema validation",
        "validate": lambda v: isinstance(v, bool),
        "real_time_setter": lambda v, mgr: mgr.config["database"].__setitem__('validation', v),
        "config_path": ("database", "validation"),
        "log_success": "Track validation set to {value}"
    },
    "database_startup": {
        "type": "bool",
        "tab": "Database",
        "label": "Start database at launch",
        "validate": lambda v: isinstance(v, bool),
        "real_time_setter": lambda v, mgr: mgr.config["database"].__setitem__('startup', v),
        "config_path": ("database", "startup"),
        "log_success": "Database startup set to {value}"
    },

    # ========= File Output =========
    "output_dir": {
        "type": "string",
        "tab": "Files",
        "label": "Data output directory",
        "placeholder": "e.g. data/",
        "real_time_setter": lambda v, mgr: mgr.config["files"].__setitem__('output_dir', v),
        "config_path": ("files", "output_dir"),
        "log_success": "Output directory set to {value}"
    },
    "tile_dir": {
        "type": "string",
        "tab": "Files",
        "label": "Tile cache directory",
        "placeholder": "e.g. mothics/static/tiles",
        "real_time_setter": lambda v, mgr: mgr.config["files"].__setitem__('tile_dir', v),
        "config_path": ("files", "tile_dir"),
        "log_success": "Tile directory set to {value}"
    },
    "logger_fname": {
        "type": "string",
        "tab": "Files",
        "label": "Log file name",
        "placeholder": "e.g. default.log",
        "real_time_setter": lambda v, mgr: mgr.config["files"].__setitem__('logger_fname', v),
        "config_path": ("files", "logger_fname"),
        "log_success": "Logger file name set to {value}"
    },
    
    # ========= Communicator =========
    "max_values": {
        "type": "int",
        "tab": "Communicator",
        "label": "Max values in buffer",
        "placeholder": "e.g. 1000",
        "validate": lambda v: v > 0,
        "config_path": ("communicator", "max_values"),
        "log_success": "Max values set to {value}"
    },
    "trim_fraction": {
        "type": "float",
        "tab": "Communicator",
        "label": "Trim fraction",
        "placeholder": "e.g. 0.5",
        "validate": lambda v: 0 < v <= 1,
        "config_path": ("communicator", "trim_fraction"),
        "log_success": "Trim fraction set to {value}"
    },

    # ========= Track =========
    "checkpoint_interval": {
        "type": "int",
        "tab": "Track",
        "label": "Checkpoint interval (s)",
        "placeholder": "e.g. 30",
        "validate": lambda v: v > 0,
        "config_path": ("track", "checkpoint_interval"),
        "log_success": "Checkpoint interval set to {value}"
    },
    "max_checkpoint_files": {
        "type": "int",
        "tab": "Track",
        "label": "Max checkpoint files",
        "placeholder": "e.g. 3",
        "validate": lambda v: v > 0,
        "config_path": ("track", "max_checkpoint_files"),
        "log_success": "Max checkpoint files set to {value}"
    },
    "track_trim_fraction": {
        "type": "float",
        "tab": "Track",
        "label": "Track trim fraction",
        "placeholder": "e.g. 0.5",
        "validate": lambda v: 0 < v <= 1,
        "config_path": ("track", "trim_fraction"),
        "log_success": "Track trim fraction set to {value}"
    },
    "max_datapoints": {
        "type": "int",
        "tab": "Track",
        "label": "Max datapoints in track",
        "placeholder": "e.g. 100000",
        "validate": lambda v: v > 0,
        "config_path": ("track", "max_datapoints"),
        "log_success": "Track max datapoints set to {value}"
    },

    # ========= CLI =========
    "cli_button_pin": {
        "type": "int",
        "tab": "CLI",
        "label": "GPIO pin for CLI button",
        "placeholder": "e.g. 21",
        "validate": lambda v: v > 0,
        "config_path": ("cli", "button_pin"),
        "log_success": "CLI button pin set to {value}"
    },

    # ========= Saving =========
    "saving_default_mode": {
        "type": "string",
        "tab": "Saving",
        "label": "Default saving mode",
        "choices": ["continuous", "on-demand"],
        "validate": lambda v: v in ["continuous", "on-demand"],
        "config_path": ("saving", "default_mode"),
        "log_success": "Saving mode set to {value}"
    }
}


# SETTINGS_REGISTRY = {
#     # ========== Aggregator Settings ==========
#     "aggregator_interval": {
#         "type": "float",
#         "tab": "Data aggregation",
#         "label": "Aggregator refresh interval (s)",
#         "placeholder": "Enter value in seconds...",
#         "validate": lambda v: v > 0,
#         "setter_name": "aggregator_refresh_rate",
#         "config_path": ("aggregator", "interval"),
#         "log_success": "Aggregator interval set to {value} seconds."
#     },

#     # ========== WebApp Settings ==========
#     "auto_refresh_table": {
#         "type": "float",
#         "tab": "Webapp",
#         "label": "Dashboard refresh interval",
#         "placeholder": "Enter value in seconds...",
#         "validate": lambda v: v > 0,
#         "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('AUTO_REFRESH_TABLE', v * 1000),
#         "config_path": ("webapp", "data_refresh"),
#         "log_success": "Auto-refresh set to {value} s"
#     },
    
#     "plot_mode": {
#         "type": "string",
#         "tab": "Webapp",
#         "label": "Current plot mode",
#         "validate": lambda v: v in ["Static", "Real-time"],
#         "choices": ["Static", "Real-time"],
#         "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('PLOT_MODE', v),
#         "config_path": ("webapp", "plot_mode"),
#         "log_success": "Plot mode changed to {value}"
#     }
# }
