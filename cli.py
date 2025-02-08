#!/usr/bin/env python3
import argh
import toml
import logging
import os
import time
import glob
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.aggregator import Aggregator
from src.comm_interface import MQTTInterface, SerialInterface, Communicator
from src.webapp import WebApp
from src.helpers import setup_logger
from src.track import Track
from src.database import Database

# =============================================================================
# Global System Manager
# =============================================================================

class SystemManager:
    def __init__(self):
        self.mode = None  # 'live' or 'replay'
        self.config = {}  # loaded from TOML file
        self.communicator = None
        self.aggregator = None
        self.webapp = None
        self.track = None  # holds the live or replay Track instance
        self.database = None
        self.logger = logging.getLogger("System Manager")
        
    def load_config(self, config_file: Optional[str]):
        if config_file and os.path.exists(config_file):
            self.config = toml.load(config_file)
            self.logger.info(f"loaded config from {config_file}")
        else:
            self.config = {}
            if config_file:
                self.logger.warning(f"config file {config_file} not found; using defaults.")

    def start_live(self, serial_config: dict, mqtt_config: dict,
                   aggregator_config: dict, webapp_config: dict):
        self.mode = "live"
        # Initialize communicator
        interfaces = {}
        if serial_config:
            interfaces[SerialInterface] = serial_config
        if mqtt_config:
            interfaces[MQTTInterface] = mqtt_config
        self.communicator = Communicator(interfaces=interfaces)
        self.communicator.connect()

        output_dir = aggregator_config.get("output_dir", "data")
        # Initialize Database (for track metadata) if needed – or simply create a new Track.
        # In our design the aggregator’s “database” will be the Track instance so that webapp
        # getters (e.g. track.get_current()) work.
        self.track = Track(mode="live", output_dir=output_dir)
        # (Optionally, you can also create a Database instance if you need to store metadata.)
        self.database = Database(output_dir, rm_thesaurus=webapp_config.get("rm_thesaurus", {}))
        
        # Create a raw-data getter for live mode.
        raw_data_getter = lambda: self.communicator.raw_data
        
        # NOTE: The correct parameter order for Aggregator is:
        # (get_raw_data, interval, database, output_dir)
        self.aggregator = Aggregator(raw_data_getter=raw_data_getter,
                                     interval=aggregator_config.get("interval", 1),
                                     database=self.track,
                                     output_dir=output_dir)
        self.aggregator.start()

        # For the webapp, we want the getter to return our Track’s current data.
        getters = {
            'database': lambda: self.track.get_current(),
            'save_status': lambda: self.track.save_mode
        }
        setters = {
            'aggregator_refresh_rate': lambda interval: self.aggregator.set_interval(interval),
            'start_save': lambda: self.track.start_run(),
            'stop_save': lambda: self.track.end_run(),
        }
        self.webapp = WebApp(getters=getters,
                             setters=setters,
                             logger_fname=webapp_config.get("logger_fname", "mockup.log"),
                             rm_thesaurus=webapp_config.get("rm_thesaurus", {}),
                             track_manager_directory=output_dir)
        self.webapp.start_in_background()
        self.logger.info("System started in LIVE mode.")

    def start_replay(self, track_file: str, aggregator_config: dict, webapp_config: dict):
        self.mode = "replay"
        output_dir = aggregator_config.get("output_dir", "data")
        self.database = Database(output_dir, rm_thesaurus=webapp_config.get("rm_thesaurus", {}))
        self.track = Track(mode="replay", output_dir=output_dir)
        self.track.load(track_file)
        # In replay mode, the getter calls self.track.get_current()
        raw_data_getter = lambda: self.track.get_current()
        self.aggregator = Aggregator(raw_data_getter=raw_data_getter,
                                     interval=aggregator_config.get("interval", 1),
                                     database=self.track,
                                     output_dir=output_dir)

        self.aggregator.start()
        getters = {
            'database': lambda: self.track.get_current(),
            'save_status': lambda: self.track.save_mode
        }
        setters = {
            'aggregator_refresh_rate': lambda interval: self.aggregator.set_interval(interval),
            'start_save': lambda: self.track.start_run(),
            'stop_save': lambda: self.track.end_run(),
        }
        self.webapp = WebApp(getters=getters,
                             setters=setters,
                             logger_fname=webapp_config.get("logger_fname", "mockup.log"),
                             rm_thesaurus=webapp_config.get("rm_thesaurus", {}),
                             track_manager_directory=output_dir)

        self.webapp.start_in_background()
        self.logger.info("System started in REPLAY mode.")

    def stop(self):
        if self.webapp:
            if hasattr(self.webapp, 'stop'):
                self.webapp.stop()
            else:
                self.logger.warning("WebApp has no stop() method; skipping webapp shutdown.")
            self.webapp = None
        if self.aggregator:
            self.aggregator.stop()
            self.aggregator = None
        if self.communicator:
            self.communicator.disconnect()
            self.communicator = None
        self.logger.info("System stopped.")

    def restart(self):
        self.logger.info("Restarting system...")
        current_config = self.config.copy()
        current_mode = self.mode
        self.stop()
        time.sleep(1)
        if current_mode == "live":
            serial_config = current_config.get("serial", {})
            mqtt_config = current_config.get("mqtt", {})
            aggregator_config = current_config.get("aggregator", {})
            webapp_config = current_config.get("webapp", {})
            self.start_live(serial_config, mqtt_config, aggregator_config, webapp_config)
        elif current_mode == "replay":
            track_file = current_config.get("track_file")
            aggregator_config = current_config.get("aggregator", {})
            webapp_config = current_config.get("webapp", {})
            self.start_replay(track_file, aggregator_config, webapp_config)
        else:
            self.logger.error("No valid mode found for restart.")

    def get_status(self):
        return {
            "mode": self.mode,
            "communicator": "running" if self.communicator else "stopped",
            "aggregator": "running" if self.aggregator else "stopped",
            "webapp": "running" if self.webapp else "stopped",
            "track": "active" if self.track else "not active",
            "database": "available" if self.database else "not initialized",
        }

# Create a global system manager instance.
system_manager = SystemManager()

# =============================================================================
# CLI commands using argh
# =============================================================================

def start(mode: str = "live",
          config: str = None,
          serial_port: str = None,
          baudrate: int = None,
          mqtt_host: str = None,
          mqtt_topics: str = None,  # comma-separated list
          interval: int = None,
          track_file: str = None):
    """
    Start the system in live or replay mode.
    For live mode, specify serial and MQTT parameters.
    For replay mode, provide a track file.
    """
    system_manager.load_config(config)
    config_data = system_manager.config

    # Set up logger using the file defined in the config (or default if none)
    logger_fname = config_data.get("webapp", {}).get("logger_fname", "mockup.log")
    setup_logger('logger', fname=logger_fname, silent=False)

    if mode == "live":
        serial_config = config_data.get("serial", {})
        if serial_port:
            serial_config["port"] = serial_port
        if baudrate:
            serial_config["baudrate"] = baudrate

        mqtt_config = config_data.get("mqtt", {})
        if mqtt_host:
            mqtt_config["hostname"] = mqtt_host
        if mqtt_topics:
            mqtt_config["topics"] = [topic.strip() for topic in mqtt_topics.split(",")]

        aggregator_config = config_data.get("aggregator", {})
        if interval:
            aggregator_config["interval"] = interval

        webapp_config = config_data.get("webapp", {})

        # Save these settings for potential restart.
        system_manager.config["serial"] = serial_config
        system_manager.config["mqtt"] = mqtt_config
        system_manager.config["aggregator"] = aggregator_config
        system_manager.config["webapp"] = webapp_config

        system_manager.start_live(serial_config, mqtt_config, aggregator_config, webapp_config)

    elif mode == "replay":
        if not track_file:
            logging.error("Track file must be provided in replay mode.")
            return
        aggregator_config = config_data.get("aggregator", {})
        if interval:
            aggregator_config["interval"] = interval
        webapp_config = config_data.get("webapp", {})

        system_manager.config["track_file"] = track_file
        system_manager.config["aggregator"] = aggregator_config
        system_manager.config["webapp"] = webapp_config

        system_manager.start_replay(track_file, aggregator_config, webapp_config)
    else:
        logging.error("Invalid mode. Choose 'live' or 'replay'.")
        return

    # Block the process so that the system keeps running (for the webapp and background tasks)
    print(f"System is running in {mode.upper()} mode. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down system...")
        system_manager.stop()

def stop():
    """Stop the running system."""
    system_manager.stop()

def restart():
    """Restart the system."""
    system_manager.restart()

def list_tracks():
    """List all tracks from the database (metadata)."""
    if system_manager.database:
        system_manager.database.list_tracks()
    else:
        print("Database not initialized.")

def select_track(index: int):
    """
    Select a track by index and display its metadata.
    """
    if system_manager.database:
        track_meta = system_manager.database.select_track(index)
        if track_meta:
            print("Selected Track Metadata:")
            for key, value in track_meta.items():
                print(f"{key}: {value}")
    else:
        print("Database not initialized.")

def show_db():
    """Show current database content (all metadata)."""
    if system_manager.database:
        entries = system_manager.database.db.all()
        print("Database entries:")
        print(entries)
    else:
        print("Database not initialized.")

def start_save():
    """Start a recording run on the Track (live mode)."""
    if system_manager.track:
        system_manager.track.start_run()
        print("Recording started.")
    else:
        print("Track not initialized.")

def stop_save():
    """Stop the current recording run on the Track."""
    if system_manager.track:
        system_manager.track.end_run()
        print("Recording stopped.")
    else:
        print("Track not initialized.")

def set_interval(new_interval: int):
    """Set the aggregator refresh interval."""
    if system_manager.aggregator:
        system_manager.aggregator.set_interval(new_interval)
        print(f"Aggregator interval set to {new_interval} s")
    else:
        print("Aggregator not running.")

def set_topics(mqtt_topics: str = None, serial_topics: str = None):
    """
    Set topics for the MQTT and Serial interfaces.
    """
    if mqtt_topics:
        topics_list = [topic.strip() for topic in mqtt_topics.split(",")]
        if system_manager.communicator:
            for iface, cfg in system_manager.communicator.interfaces.items():
                if cfg.get("hostname"):
                    cfg["topics"] = topics_list
                    logging.info("MQTT topics updated.")
        print("MQTT topics set.")
    if serial_topics:
        topics_list = [topic.strip() for topic in serial_topics.split(",")]
        if system_manager.communicator:
            for iface, cfg in system_manager.communicator.interfaces.items():
                if cfg.get("port"):
                    cfg["topics"] = topics_list
                    logging.info("Serial topics updated.")
        print("Serial topics set.")

def status():
    """Display the current system status."""
    st = system_manager.get_status()
    print("System Status:")
    for key, value in st.items():
        print(f"{key}: {value}")

def logs():
    """Display recent logs from the log file."""
    log_file = str(system_manager.config.get("webapp", {}).get("logger_fname", "mockup.log"))
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            print(f.read())
    else:
        print("Log file not found.")

def update_metadata(filename: str, key: str, value: str):
    """
    Update metadata for a track in the Database.
    Example: update the remote_units of a track.
    """
    if system_manager.database:
        system_manager.database.update_track_metadata(filename, {key: value})
        print(f"Metadata for {filename} updated: {key} -> {value}")
    else:
        print("Database not initialized.")

def dump_config(outfile: str):
    """
    Dump the current system configuration to a TOML file.
    
    Usage:
        python script.py dump_config --outfile my_settings_dump.toml
    """
    try:
        with open(outfile, 'w') as f:
            f.write(toml.dumps(system_manager.config))
        print(f"Configuration dumped to {outfile}")
    except Exception as e:
        print(f"Error dumping configuration: {e}")

# =============================================================================
# Main: Register commands with argh.
# =============================================================================

parser = argh.ArghParser()
parser.add_commands([
    start, stop, restart, list_tracks, select_track, show_db,
    start_save, stop_save, set_interval, set_topics, status, logs,
    update_metadata, dump_config
])

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    parser.dispatch()
