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
from .comm_interface import MQTTInterface, SerialInterface, Communicator
from .webapp import WebApp
from .helpers import setup_logger, tipify, check_cdn_availability, download_cdn, check_internet_connectivity
from .track import Track
from .database import Database


# Default configuration values to be used if `config.toml` cannot be found
DEFAULT_CONFIG = {
    "serial": {
        "port1": {
            "name": "Port 1",
            "port": "/dev/ttyACM0",
            "baudrate": 9600,
            "topics": "rm2/wind/speed"
        }
    },
    "mqtt": {
        "hostname": "test.mosquitto.org",
        "topics": ["rm1/gps/lat", "rm1/gps/long"]
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
    "files": {
        "logger_fname": "default.log",
        "cdn_dir": "mothics/static",
        "output_dir": "data"
    },
    "webapp": {
        "data_refresh": 2,
        "timeout_offline": 60,
        "timeout_noncomm": 30,
        "rm_thesaurus": {
            "rm1": "GPS+IMU",
            "rm2": "Anemometer"
        }
    },
    "cli": {
        "button_pin": 21
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

    def _setup_logger(self, logger_fname, level=logging.INFO):
        setup_logger('logger', fname=logger_fname, silent=False)
        logging.basicConfig(level=level)
        self.logger = logging.getLogger("SystemManager")

    def load_config(self):
        """Loads the configuration file and merges it with defaults."""
        config_from_file = {}
        
        if os.path.exists(self.config_file):
            try:
                config_from_file = toml.load(self.config_file)
            except Exception as e:
                # Initialize the logger even if config loading fails
                self._setup_logger(self.config["files"]["logger_fname"])
                
                self.logger.warning(f"error loading configuration from {self.config_file}: {e}. Using defaults.")
        else:
            # If the config file doesn't exist, log a warning but keep using defaults
            self._setup_logger(self.config["files"]["logger_fname"])
            
            self.logger.info(f"no configuration file '{self.config_file}' found. Using defaults.")

        # Merge loaded config into defaults (config values overwrite defaults)
        for section, defaults in DEFAULT_CONFIG.items():
            self.config[section] = {**defaults, **config_from_file.get(section, {})}

        # Set up the logger using the final merged config
        logger_fname = self.config["files"]["logger_fname"]
        self._setup_logger(logger_fname)
        self.logger.info(f"configuration loaded successfully from {self.config_file if config_from_file else 'defaults'}.")
        
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

    def initialize_database(self):
        """ Initializes the database. """                                      
        output_dir = self.config["files"]["output_dir"]
        rm_thesaurus = self.config["webapp"]["rm_thesaurus"]
                               
        # Start database
        self.database = Database(output_dir, rm_thesaurus=rm_thesaurus)
        
    def initialize_common_components(self, mode, track_file=None):
        """ Initializes shared components for live and replay modes. """
        self.mode = mode
        self.logger.info(f"initializing {mode} mode")

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
            # Initialize Webapp
            getters = {
                'database': lambda: self.track.get_current(),
                'save_status': lambda: self.track.save_mode
            }
            setters = {
                'aggregator_refresh_rate': lambda interval: self.aggregator.set_interval(interval),
                'start_save': lambda: self.track.start_run(),
                'stop_save': lambda: self.track.end_run(),
            }
            self.webapp = WebApp(
                getters=getters,
                setters=setters,
                auto_refresh_table=self.config["webapp"]["data_refresh"],
                logger_fname=self.config["files"]["logger_fname"],
                rm_thesaurus=self.config["webapp"]["rm_thesaurus"],
                data_thesaurus=self.config["webapp"]["data_thesaurus"],
                timeout_offline=self.config["webapp"]["timeout_offline"],
                timeout_noncomm=self.config["webapp"]["timeout_noncomm"],
                track_manager_directory=self.config["files"]["output_dir"]
            )
            self.webapp.run()

    def start_live(self):
        self.initialize_common_components("live")

        interfaces = {}

        # Initialize serial interfaces
        interfaces[SerialInterface] = list(self.config['serial'].values())
        
        # Initialize MQTT interfaces
        interfaces[MQTTInterface] = self.config["mqtt"]

        # Initialize Communicator
        try:
            self.communicator = Communicator(interfaces=interfaces,
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
        if self.webapp:
            try:
                self.webapp.stop()
                self.webapp = None
            except:
                self.logger.warning('cannot stop webapp')
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

    def get_status(self):
        return {
            "mode": self.mode,
            "communicator": "running" if self.communicator else "stopped",
            "aggregator": "running" if self.aggregator else "stopped",
            "webapp": "running" if self.webapp else "stopped",
            "track": "active" if self.track else "not active",
            "database": "available" if self.database else "not initialized",
        }
