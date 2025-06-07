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

 - `type`: type expected from user input; one of "string", "float", "int", "bool", "button", "taglist", "kvtable"
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
from functools import wraps


def mirror_to_config(path):
    """
    Decorator factory.
    `path` is the tuple from SETTINGS_REGISTRY
    describing where in CONFIG_DATA to write the new value.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(value, mgr):
            # 1) Run the live effect
            result = fn(value, mgr)

            # 2) Persist into the Flask app’s CONFIG_DATA
            cfg = mgr.webapp.app.config["CONFIG_DATA"]
            node = cfg
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = value

            return result
        return wrapper
    return decorator

# Helpers
@mirror_to_config(("webapp", "data_thesaurus"))
def set_data_thesaurus(v, mgr):
    mgr.webapp.app.config['DATA_THESAURUS'] = v
    

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
    "data_thesaurus": {
        "type": "kvtable",
        "tab": "Webapp",
        "label": "Sensor values aliases",
        "real_time_setter": set_data_thesaurus,
        "config_path": ("webapp", "data_thesaurus"),
        "log_success": "Data thesaurus updated."
    },
    "hidden_data_plots": {
        "type": "taglist",
        "tab": "Webapp",
        "label": "Hidden sensor values",
        "real_time_setter": lambda v, mgr: mgr.webapp.app.config.__setitem__('HIDDEN_DATA_PLOTS', v),
        "config_path": ("webapp", "hidden_data_plots"),
        "validate": lambda raw: True,
        "log_success": "Hidden-data list updated."
    },
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
    },
    # ============== IMU ================
    "yaw_offset": {
        "type": "float",
        "tab": "Calibration",
        "label": "Yaw offset (°)",
        "placeholder": "0 → no change",
        "validate": lambda v: -180.0 <= v <= 180.0,
        "real_time_setter": (
            lambda v, mgr:
            mgr.communicator
            .preprocessors["AngleOffset_default"]      # ← class name or instance name
            .set_offset("rm1/imu/yaw", v)
        ),
        "config_path": ("angle_offset", "rm1/imu/yaw"),
        "log_success": "Yaw offset set to {value}°"
    },
    
    "pitch_offset": {
        "type": "float",
        "tab": "Calibration",
        "label": "Pitch offset (°)",
        "placeholder": "0 → no change",
        "validate": lambda v: -90.0 <= v <= 90.0,
        "real_time_setter": (
            lambda v, mgr:
            mgr.communicator
            .preprocessors["AngleOffset_default"]
            .set_offset("rm1/imu/pitch", v)
        ),
        "config_path": ("angle_offset", "rm1/imu/pitch"),
        "log_success": "Pitch offset set to {value}°"
    },
    
    "roll_offset": {
        "type": "float",
        "tab": "Calibration",
        "label": "Roll offset (°)",
        "placeholder": "0 → no change",
        "validate": lambda v: -180.0 <= v <= 180.0,
        "real_time_setter": (
            lambda v, mgr:
            mgr.communicator
            .preprocessors["AngleOffset_default"]
            .set_offset("rm1/imu/roll", v)
        ),
        "config_path": ("angle_offset", "rm1/imu/roll"),
        "log_success": "Roll offset set to {value}°"
    },
    "zero_imu": {
        "type": "button",
        "tab": "Calibration",
        "label": "Zero yaw / pitch / roll (use latest data)",
        "real_time_setter": (
            lambda v, mgr: mgr.communicator.preprocessors["AngleOffset_default"].calibrate()
        ),
        "config_path": ("angle_offset", "zero_imu"),
        "log_success": "IMU angles zeroed"
    },
    "reset_imu_offset": {
        "type": "button",
        "tab": "Calibration",
        "label": "Reset all IMU offsets to 0",
        "real_time_setter": (
            lambda v, mgr: mgr.communicator.preprocessors["AngleOffset_default"].reset_offsets()
        ),
        "config_path": ("angle_offset", "reset_imu_offset"),
        "log_success": "IMU offsets cleared"
    },
}
