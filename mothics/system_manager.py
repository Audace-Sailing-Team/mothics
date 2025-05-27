#!/usr/bin/env python3
import copy
import requests
import psutil
import argh
import toml
import logging
import os
import time
import glob
import json
import csv
import sys
import shutil
import threading
import subprocess
from tabulate import tabulate
from cmd import Cmd
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .aggregator import Aggregator
from .comm_interface import MQTTInterface, SerialInterface, GPIOInterface, Communicator, available_interfaces
from .preprocessors import UnitConversion, available_processors
from .webapp import WebApp
from .helpers import setup_logger, tipify, check_cdn_availability, download_cdn, check_internet_connectivity, download_tiles, list_required_tiles, get_device_platform, parse_uc_table
from .track import Track
from .database import Database


# Default configuration values to be used if `config.toml` cannot be found
DEFAULT_CONFIG = {
    "serial": {
        "port1": {
            "name": "Fallback",
            "port": "/dev/ttyACM0",
            "baudrate": 9600,
            "topics": "rm2/wind/speed"
        }
    },
    "mqtt": {
        "hostname": "test.mosquitto.org",
        "topics": ["rm1/gps/lat", "rm1/gps/long"]
    },
    "gpio": {
    },
    "communicator": {
        "max_values": 1e3,
        "trim_fraction": 0.5
    },
    "aggregator": {
        "interval": 1
    },
    "saving": {
        "default_mode": "continuous"
    },
    "track": {
        "checkpoint_interval": 30,
        "max_checkpoint_files": 3,
        "trim_fraction": 0.5,
        "max_datapoints": 1e5
    },
    "database":{
        "validation": True,
        "startup": False
    },
    "files": {
        "logger_fname": "default.log",
        "cdn_dir": "mothics/static",
        "output_dir": "data",
        "tile_dir": "mothics/static/tiles"
    },
    "webapp": {
        "data_refresh": 2,
        "timeout_offline": 60,
        "timeout_noncomm": 30,
        "rm_thesaurus": {
            "rm1": "GPS+IMU",
            "rm2": "Anemometer"
        },
        "data_thesaurus": None,
        "hidden_data_cards": None,
        "hidden_data_plots": None,
        "gps": {
            "lat_range": [45.5, 45.8],
            "lon_range": [13.5, 14.0],
            "zoom_levels": [13, 14, 15],
            "track_variable":'speed',
            "track_thresholds": None,
            "track_colors": None,
            "track_units": 'm/s',
            "track_history": 10
        },
    },
    "cli": {
        "button_pin": 21,
        "startup_commands": None
    }
}


# System manager
class SystemManager:
    def __init__(self, config_file="config.toml"):
        self.mode = None  # "live" or "replay"
        self.config_file = config_file
        self.communicator = None
        self.aggregator = None
        self.webapp = None
        self.track = None
        self.database = None
        self.config = copy.deepcopy(DEFAULT_CONFIG)  # Always start with default settings as a failsafe

        self.load_config()
        self.device_type = get_device_platform()

    def _setup_logger(self, logger_fname, level=logging.INFO):
        setup_logger('logger', fname=logger_fname, silent=False)
        logging.basicConfig(level=level)
        self.logger = logging.getLogger("SystemManager")

    def load_config(self):
        """Load TOML and overlay DEFAULT_CONFIG, but keep new sections intact."""
        cfg_file = {}
        if os.path.exists(self.config_file):
            try:
                cfg_file = toml.load(self.config_file)
            except Exception as e:
                self._setup_logger(self.config["files"]["logger_fname"])
                self.logger.warning(
                    f"error loading {self.config_file}: {e}. Using defaults."
                )
        else:
            self._setup_logger(self.config["files"]["logger_fname"])
            self.logger.info(
                f"no configuration file '{self.config_file}' found. Using defaults."
            )

        # --- merge --------------------------------------------------------
        # 1) start with a *copy* of the defaults
        self.config = {k: v.copy() if isinstance(v, dict) else v
                       for k, v in DEFAULT_CONFIG.items()}

        # 2) overlay everything that came from the file
        for section, data in cfg_file.items():
            if (isinstance(data, dict)
                    and isinstance(self.config.get(section), dict)):
                self.config[section].update(data)   # deep-merge dicts
            else:
                self.config[section] = data         # new or non-dict section

        # logger is ready now
        self._setup_logger(self.config["files"]["logger_fname"])
        self.logger.info("configuration loaded (file + defaults)")
        
    # def load_config(self):
    #     """Loads the configuration file and merges it with defaults."""
    #     config_from_file = {}
        
    #     if os.path.exists(self.config_file):
    #         try:
    #             config_from_file = toml.load(self.config_file)
    #         except Exception as e:
    #             # Initialize the logger even if config loading fails
    #             self._setup_logger(self.config["files"]["logger_fname"])
                
    #             self.logger.warning(f"error loading configuration from {self.config_file}: {e}. Using defaults.")
    #     else:
    #         # If the config file doesn't exist, log a warning but keep using defaults
    #         self._setup_logger(self.config["files"]["logger_fname"])
            
    #         self.logger.info(f"no configuration file '{self.config_file}' found. Using defaults.")

    #     # Merge loaded config into defaults (config values overwrite defaults)
    #     for section, defaults in DEFAULT_CONFIG.items():
    #         self.config[section] = {**defaults, **config_from_file.get(section, {})}

    #     # Set up the logger using the final merged config
    #     logger_fname = self.config["files"]["logger_fname"]
    #     self._setup_logger(logger_fname)
    #     self.logger.info(f"configuration loaded successfully from {self.config_file if config_from_file else 'defaults'}.")
        
    def initialize_cdns(self):
        """ Initializes CDNs for webapp display """
        # Get CDN URLs from configuration
        cdn_urls = self.config["webapp"]["cdns"]
        
        if not cdn_urls:
            self.logger.warning("no CDN URLs specified in configuration. Skipping CDN initialization")
            return

        # Check if required CDN files are already cached locally
        cdn_dir = os.path.join(os.getcwd(), self.config["files"]["cdn_dir"])
        missing_files = check_cdn_availability(urls=cdn_urls, outdir=cdn_dir)
        if not missing_files:
            self.logger.info("all required CDN files are cached")
            return
        
        # Check internet connectivity before downloading missing files
        if not check_internet_connectivity():
            self.logger.warning("Internet connectivity is not available. Cannot download missing CDNs.")
            self.logger.warning("Proceeding without updated CDN files")
            return

        # Download missing CDN files
        self.logger.info(f"Internet available. Downloading missing CDN files to {cdn_dir}")
        download_cdn(urls=cdn_urls, outdir=cdn_dir)

    def initialize_tiles(self):
        """Download map tiles for GPS map visualization."""
        # Check for internet availability
        if not check_internet_connectivity():
            self.logger.warning("Internet connectivity is not available. Cannot download map tiles.")
            return
        
        # Get lat/long range from config 
        lat_range = self.config["webapp"]["gps"]["lat_range"]
        lon_range = self.config["webapp"]["gps"]["lon_range"]
        zoom_levels = self.config["webapp"]["gps"]["zoom_levels"]
        output_dir = self.config["files"]["tile_dir"]
        os.makedirs(output_dir, exist_ok=True)

        # Get map tiles to download based on lat/long range
        try:
            self.logger.info(f"downloading map tiles for lat={lat_range}, lon={lon_range}, zoom={zoom_levels}")
            self.logger.info(f"number tiles to download: {len(list_required_tiles(lat_range, lon_range, zoom_levels))} in ~{len(list_required_tiles(lat_range, lon_range, zoom_levels)) * 0.25}s")
            download_tiles(lat_range=tuple(lat_range),
                           lon_range=tuple(lon_range),
                           zoom_levels=zoom_levels,
                           output_dir=output_dir)
            self.logger.info(f"tile download completed and stored in {output_dir}")
        except Exception as e:
            self.logger.warning(f"error while downloading map tiles: {e}")
        
    def initialize_database(self):
        """ Initializes the database. """                                      
        # Start database
        self.database = Database(self.config["files"]["output_dir"],
                                 rm_thesaurus=self.config["webapp"]["rm_thesaurus"],
                                 validation=self.config["database"]["validation"])
        
    def initialize_common_components(self, mode, track_file=None):
        """ Initializes shared components for live and replay modes. """
        self.mode = mode
        self.logger.info(f"initializing {mode} mode")

        # Start database if required at startup
        if self.config["database"]["startup"]:
            try:
                self.initialize_database()
            except Exception as e:
                self.logger.critical(f"error in database initialization, got {e}" )

        # Initialize track
        self.track = Track(mode=mode,
                           checkpoint_interval=self.config["track"]["checkpoint_interval"],
                           max_checkpoint_files=self.config["track"]["max_checkpoint_files"],
                           trim_fraction=self.config["track"]["trim_fraction"],
                           max_datapoints=self.config["track"]["max_datapoints"],
                           output_dir=self.config["files"]["output_dir"])
        # Load from file if specified
        if mode == "replay" and track_file:
            self.track.load(track_file)
        # Set default saving mode
        self.track.save_mode = self.config["saving"]["default_mode"]

    def initialize_aggregator(self, raw_data_getter):
        """ Initializes the aggregator with the given raw data source. """
        self.aggregator = Aggregator(
            raw_data_getter=raw_data_getter,
            interval=self.config["aggregator"]["interval"],
            database=self.track,
            output_dir=self.config["files"]["output_dir"]
        )
        self.aggregator.start()

    def initialize_webapp(self):
        """ Initializes the web application with necessary getters and setters. """
        if not self.webapp:
            # Initialize CDNs
            self.initialize_cdns()
            # Initialize tiles
            self.initialize_tiles()
            
            # Pass all getter functions
            getters = {
                'database': lambda: self.track.get_current(),
                'save_status': lambda: self.track.save_mode
            }
            
            # Pass all setter functions
            setters = {
                'aggregator_refresh_rate': lambda interval: self.aggregator.set_interval(interval),
                'start_save': lambda: self.track.start_run(),
                'stop_save': lambda: self.track.end_run(),
            }

            # Initialize Webapp
            self.webapp = WebApp(
                getters=getters,
                setters=setters,
                auto_refresh_table=self.config["webapp"]["data_refresh"],
                logger_fname=self.config["files"]["logger_fname"],
                rm_thesaurus=self.config["webapp"]["rm_thesaurus"],
                data_thesaurus=self.config["webapp"]["data_thesaurus"],
                hidden_data_cards=self.config["webapp"]["hidden_data_cards"],
                hidden_data_plots=self.config["webapp"]["hidden_data_plots"],
                timeout_offline=self.config["webapp"]["timeout_offline"],
                timeout_noncomm=self.config["webapp"]["timeout_noncomm"],
                track_manager=self.database,
                track_manager_directory=self.config["files"]["output_dir"],
                gps_tiles_directory=self.config["files"]["tile_dir"],
                track_variable=self.config["webapp"]["gps"]["track_variable"],
                track_thresholds=self.config["webapp"]["gps"]["track_thresholds"],
                track_colors=self.config["webapp"]["gps"]["track_colors"],
                track_units=self.config["webapp"]["gps"]["track_units"],
                track_history_minutes=self.config["webapp"]["gps"]["track_history"],
                instance_dir=os.path.dirname(sys.modules['__main__'].__file__),
                out_dir=self.config["files"]["output_dir"],
                system_manager=self
            )
            # self.webapp.run()
            t = threading.Thread(target=self.webapp.serve, daemon=True, name="WaitressServer")
            t.start()

    def start_live(self):
        self.initialize_common_components("live")

        # Initialize interfaces
        interfaces = {}

        for section_name, section_cfg in self.config.items():
            iface_cls = available_interfaces.get(section_name)
            # Ignore unknown/unavailable interfaces
            if iface_cls is None:
                continue
            
            # Skip GPIO on non-Raspberry Pi targets
            if iface_cls is GPIOInterface and self.device_type != "rpi":
                continue
            
            # Distinguish “one interface” vs “many sub-interfaces”
            if isinstance(section_cfg, dict) and section_cfg and all(
                    isinstance(v, dict) for v in section_cfg.values()
            ):
                # Many sub-interfaces (serial, gpio, …)
                interfaces[iface_cls] = list(section_cfg.values())
            else:
                # Single interface (mqtt, …)
                interfaces[iface_cls] = section_cfg

        # Initialize preprocessors
        preprocessors = {}

        for section_name, section_cfg in self.config.items():
            proc_cls = available_processors.get(section_name)
            if proc_cls is None:
                continue

            if proc_cls is UnitConversion:
                # translate TOML to kwargs with our helper
                kwargs = parse_uc_table(section_cfg)
                
                # allow more than one instance (rare, but keeps the API uniform)
                preprocessors.setdefault(proc_cls, []).append(kwargs)
                continue
            
            # Distinguish “one interface” vs “many sub-interfaces”.
            if isinstance(section_cfg, dict) and section_cfg and all(
                    isinstance(v, dict) for v in section_cfg.values()
            ):
                # Many sub-interfaces (serial, gpio, …)
                preprocessors[proc_cls] = list(section_cfg.values())
            else:
                # Single interface (mqtt, …)
                preprocessors[proc_cls] = section_cfg
                
        # Initialize Communicator
        try:
            self.communicator = Communicator(interfaces=interfaces,
                                             preprocessors=preprocessors,
                                             max_values=self.config["communicator"]["max_values"],
                                             trim_fraction=self.config["communicator"]["trim_fraction"])
        except Exception as e:
            self.logger.critical(f"error in initializing communicator, got {e}")

        self.communicator.connect()

        # Set up aggregator
        raw_data_getter = lambda: self.communicator.raw_data
        self.initialize_aggregator(raw_data_getter)

        # Set up web app
        self.initialize_webapp()

        self.mode = 'live'
        self.logger.info("live mode started")

    def start_replay(self, track_file=None):
        self.initialize_common_components("replay", track_file, aggregator_config, webapp_config)

        # Set up aggregator
        raw_data_getter = lambda: self.track.get_current()
        self.initialize_aggregator(raw_data_getter)

        # Set up web app
        self.initialize_webapp()

        self.mode = 'replay'
        self.logger.info("replay mode started")

    def stop(self):
        self.logger.info("stopping system")
        if self.aggregator:
            self.aggregator.stop()
            self.aggregator = None
        if self.communicator:
            self.communicator.disconnect()
            self.communicator = None
        self.logger.info("system stopped")

    def restart(self, mode=None, reload_config=False):
        self.logger.info("restarting system")
        if reload_config:
            self.logger.info("reloading configuration from file before restart")
            self.load_config()
        
        if mode is None:
            mode = self.mode
        self.stop()
        time.sleep(1)
        if mode == "live":
            self.start_live()
        elif mode == "replay":
            self.start_replay()
        else:
            self.logger.error(f"no valid mode found for restart, got: {mode}")
            
        # Restart bokeh server if webapp is available
        if self.webapp is not None and self.webapp.bokeh_thread is not None:
            self.webapp.restart_bokeh_server()

    def get_status(self):
        if self.webapp:
            bokeh_status = self.webapp.bokeh_thread
        else:
            bokeh_status = False
        return {
            "mode": self.mode,
            "communicator": "running" if self.communicator else "stopped",
            "aggregator": "running" if self.aggregator else "stopped",
            "webapp": "running" if self.webapp else "stopped",
            "bokeh server": "running" if bokeh_status else "stopped",
            "track": "active" if self.track else "not active",
            "database": "available" if self.database else "not initialized",
        }
