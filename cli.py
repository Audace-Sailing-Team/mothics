#!/usr/bin/env python3
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

from mothics.aggregator import Aggregator
from mothics.comm_interface import MQTTInterface, SerialInterface, Communicator
from mothics.webapp import WebApp
from mothics.helpers import setup_logger, tipify, check_cdn_availability, download_cdn
from mothics.track import Track
from mothics.database import Database


class SystemManager:
    def __init__(self, config_file="config.toml"):
        self.mode = None  # "live" or "replay"
        self.config = {}
        self.communicator = None
        self.aggregator = None
        self.webapp = None
        self.track = None
        self.database = None
        self.load_config(config_file)

    def _setup_logger(self, logger_fname):
        setup_logger('logger', fname=logger_fname, silent=False)
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("SystemManager")
        
    def load_config(self, config_file):
        if os.path.exists(config_file):
            try:
                self.config = toml.load(config_file)
                
                # Setup logger
                logger_fname = self.config.get("logging", {}).get("logger_fname", os.path.join(os.getcwd(), 'default.log'))    
                self._setup_logger(logger_fname)
                
                self.logger.info(f"loaded configuration from {config_file}")
            except Exception as e:
                self.logger = logging.getLogger("SystemManager")
                self.logger.critical(f"error loading configuration from {config_file}: {e}")
        else:
            self.logger.info(f"no configuration file '{config_file}' found. Using defaults.")

    def initialize_cdns(self):
        """ Initializes CDNs for webapp display """
        # Get CDN URLs from configuration
        cdn_urls = self.config.get("webapp", {}).get("cdns", [])
        if not cdn_urls:
            self.logger.warning("no CDN URLs specified in configuration. Skipping CDN initialization")
            return

        # Check if required CDN files are already cached locally
        cdn_dir = os.path.join(os.getcwd(), self.config.get("webapp", {}).get("cdn_directory", []))
        missing_files = check_cdn_availability(urls=cdn_urls, outdir=cdn_dir)
        if not missing_files:
            self.logger.info("all required CDN files are cached")
            return

        # Check internet connectivity before attempting to download missing files
        try:
            # Use a HEAD request to a well-known website to verify connectivity.
            response = requests.head("https://www.google.com", timeout=5)
            if response.status_code != 200:
                raise Exception(f"connectivity check returned unexpected status code: {response.status_code}")
        except Exception as e:
            self.logger.warning(f"internet connectivity is not available. Cannot download missing CDNs, got: {e}")
            self.logger.warning("proceeding without updated CDN files")
            return

        # Download missing CDN files using the existing download_cdn function
        self.logger.info(f"internet available. Downloading missing CDN files to {cdn_dir}")
        download_cdn(urls=cdn_urls, outdir=cdn_dir)
    
    def initialize_database(self, aggregator_config=None, webapp_config=None):
        """ Initializes the database. """
        # Get configs
        webapp_config = webapp_config or self.config.get("webapp", {"logger_fname": "mockup.log"})
        aggregator_config = aggregator_config or self.config.get("aggregator", {"interval": 1, "output_dir": "data"})
        output_dir = aggregator_config.get("output_dir", "data")

        # Start database
        self.database = Database(output_dir, rm_thesaurus=webapp_config.get("rm_thesaurus", {}))        
        
    def initialize_common_components(self, mode, track_file=None, aggregator_config=None, webapp_config=None):
        """ Initializes shared components for live and replay modes. """
        self.mode = mode
        self.logger.info(f"Initializing {mode} mode")

        aggregator_config = aggregator_config or self.config.get("aggregator", {"interval": 1, "output_dir": "data"})
        webapp_config = webapp_config or self.config.get("webapp", {"logger_fname": "mockup.log"})
        output_dir = aggregator_config.get("output_dir", "data")

        self.initialize_database()

        # Initialize track
        self.track = Track(mode=mode, output_dir=output_dir)
        if mode == "replay" and track_file:
            self.track.load(track_file)

        return aggregator_config, webapp_config, output_dir

    def initialize_aggregator(self, raw_data_getter, aggregator_config, output_dir):
        """ Initializes the aggregator with the given raw data source. """
        self.aggregator = Aggregator(
            raw_data_getter=raw_data_getter,
            interval=aggregator_config.get("interval", 1),
            database=self.track,
            output_dir=output_dir
        )
        self.aggregator.start()

    def initialize_webapp(self, webapp_config, output_dir):
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
                logger_fname=webapp_config.get("logger_fname", "mockup.log"),
                rm_thesaurus=webapp_config.get("rm_thesaurus", {}),
                track_manager_directory=output_dir
            )
            self.webapp.run()

    def start_live(self, serial_config=None, mqtt_config=None, aggregator_config=None, webapp_config=None):
        aggregator_config, webapp_config, output_dir = self.initialize_common_components("live", aggregator_config=aggregator_config, webapp_config=webapp_config)

        # Initialize interfaces and communicator
        serial_config = serial_config or self.config.get("serial", {})
        mqtt_config = mqtt_config or self.config.get("mqtt", {})
        interfaces = {}
        if serial_config:
            interfaces[SerialInterface] = serial_config
        if mqtt_config:
            interfaces[MQTTInterface] = mqtt_config

        self.communicator = Communicator(interfaces=interfaces)
        self.communicator.connect()

        # Set up aggregator
        raw_data_getter = lambda: self.communicator.raw_data
        self.initialize_aggregator(raw_data_getter, aggregator_config, output_dir)

        # Set up web app
        self.initialize_webapp(webapp_config, output_dir)

        self.mode = 'live'
        self.logger.info("live mode started")

    def start_replay(self, track_file=None, aggregator_config=None, webapp_config=None):
        aggregator_config, webapp_config, output_dir = self.initialize_common_components("replay", track_file, aggregator_config, webapp_config)

        # Set up aggregator
        raw_data_getter = lambda: self.track.get_current()
        self.initialize_aggregator(raw_data_getter, aggregator_config, output_dir)

        # Set up web app
        self.initialize_webapp(webapp_config, output_dir)

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

    def restart(self, mode=None):
        self.logger.info("restarting system")
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


# Global instance of SystemManager
system_manager = SystemManager()


# CLI
class MothicsCLI(Cmd):
    prompt = '(mothics) '
    intro = """
    ==============================================
    Mothics - Moth Analytics 
    Iacopo Ricci - Audace Sailing Team - 2025
    
    Default SSH address: \t 192.168.42.1
    Default dashboard address: \t 192.168.42.1:5000
    Type "help" for available commands.
    Type "exit" or <CTRL-D> to quit.
    ==============================================
    """
    
    def do_start(self, args):
        """
        Start the system.
        Usage:
            start live
            start replay <track_file>
            start database
        """
        parts = args.split()
        if not parts:
            print("Please specify a mode: live, replay or database")
            return

        mode = parts[0].lower()
        if mode == "live":
            system_manager.start_live()
        elif mode == "replay":            
            # Start database
            if not system_manager.database:
                system_manager.initialize_database()

            if len(parts) <= 1:
                print("Please specify a track filename")
                print("Available tracks:")
                self.do_list_tracks(args)
                return
                
            # Handle indices
            fname = tipify(parts[1])
            track_file = system_manager.database.get_track_path(fname)
            system_manager.start_replay(track_file=track_file)
        elif mode == "database":
            system_manager.initialize_database()
        else:
            print("Invalid mode. Please choose 'live' or 'replay'.")

    def do_stop(self, args):
        """Stop the running system."""
        system_manager.stop()

    def do_restart(self, args):
        """Restart the system."""
        system_manager.restart()

    def do_status(self, args):
        """Display the current system status."""
        status = system_manager.get_status()
        for key, value in status.items():
            print(f"{key}: {value}")

    def do_list_tracks(self, args):
        """List tracks from Database"""
        if not system_manager.database:
            system_manager.initialize_database()
        system_manager.database.list_tracks()

    def do_select_track(self, args):
        """
        Select a track by index and display its metadata.
        """
        parts = args.split()
        if not parts:
            print("Please specify a track index")
            return
        
        index = tipify(parts[0])

        if not isinstance(index, int):
            print("Please specify a track index")
            return
        
        if system_manager.database:
            track_meta = system_manager.database.select_track(index)
            if track_meta:
                print("Selected Track Metadata:")
                for key, value in track_meta.items():
                    print(f"{key}: {value}")
        else:
            print("Database not initialized.")

    def do_log(self, args):
        """
        Display or delete logs from the log file.
        Usage:
            log show
            log clear
        """        
        log_file = str(system_manager.config.get("webapp", {}).get("logger_fname", "default.log"))

        parts = args.split()
        if not parts:
            print("Please specify a mode: show or clear")
            return

        if parts[0] == 'show':
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    print(f.read())
            else:
                print("Log file not found.")
        elif parts[0] == 'clear':
            if os.path.exists(log_file):
                with open(log_file, "w") as f:
                    open(log_file, 'w').close()
            else:
                print("Log file not found.")

    def do_resources(self, args):
        """Show resource usage of the CLI and its dependencies."""
        process = psutil.Process(os.getpid())  # Get current process info
        mem_info = process.memory_info()
        cpu_usage = process.cpu_percent(interval=0.1)
        open_files = len(process.open_files())
        threads = process.num_threads()

        # Prepare data for tabulation
        data = [
            ["CPU usage (estimate)", f"{cpu_usage:.2f} %"],
            ["Memory usage (RSS)", f"{mem_info.rss / 1024 ** 2:.2f} MB"],
            ["Open file descriptors", open_files],
            ["Thread count", threads]
        ]

        # Print as a table
        print(f'\n{tabulate(data, headers=["Resource", "Usage"], tablefmt="github")}')

    def do_shell(self, args):
        """Execute shell commands without exiting the CLI.
        
        Usage:
            shell <command>
            !<command>  (shortcut)
        """
        if not args:
            print("Please provide a shell command.")
            return

        try:
            result = subprocess.run(args, shell=True, text=True, capture_output=True)
            print(result.stdout)  # Print command output
            if result.stderr:
                print("Error:", result.stderr)
        except Exception as e:
            print(f"Error executing command: {e}")

    def default(self, line):
        """Allows using '!' as a shortcut to run shell commands."""
        if line.startswith("!"):
            self.do_shell(line[1:])
        else:
            print(f"Unknown command: {line}")

        
    def do_exit(self, args):
        """Exit the CLI stopping processes."""
        print("Exiting CLI.")
        try:
            self.do_stop(args)
            return True
        except:
            return False
        
    def do_kill(self, args):
        """Exit the CLI abruptly."""
        print("Exiting CLI abruptly.")
        return True
    
    def do_EOF(self, args):
        """Exit on Ctrl-D (EOF)."""
        print("Exiting CLI.")
        try:
            self.do_stop(args)
            return True
        except:
            return False

if __name__ == '__main__':
    cli = MothicsCLI()
    if len(sys.argv) > 1:
        # Execute the command passed as argument
        command = " ".join(sys.argv[1:])
        cli.onecmd(command)
    # Now drop into the interactive CLI
    cli.cmdloop()
