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

from mothics.aggregator import Aggregator
from mothics.comm_interface import MQTTInterface, SerialInterface, Communicator
from mothics.webapp import WebApp
from mothics.helpers import setup_logger, tipify, check_cdn_availability, download_cdn, check_internet_connectivity
from mothics.track import Track
from mothics.database import Database


# Default configuration values to be used if `config.toml` cannot be found
DEFAULT_CONFIG = {
    "serial": {
        "port": "/dev/ttyACM0",
        "baudrate": 9600,
        "topics": "rm2/wind/speed"
    },
    "mqtt": {
        "hostname": "test.mosquitto.org",
        "topics": ["rm1/gps/lat", "rm1/gps/long"]
    },
    "aggregator": {
        "interval": 1
    },
    "saving": {
        "default_mode": "continuous"
    },
    "files": {
        "logger_fname": "default.log",
        "cdn_dir": "mothics/static",
        "output_dir": "data"
    },
    "webapp": {
        "rm_thesaurus": {
            "rm1": "GPS+IMU",
            "rm2": "Anemometer"
        }
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
                               
        output_dir = self.config["files"]["output_dir"]
        self.initialize_database()

        # Initialize track
        self.track = Track(mode=mode, output_dir=output_dir)
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
                logger_fname=self.config["files"]["logger_fname"],
                rm_thesaurus=self.config["webapp"]["rm_thesaurus"],
                track_manager_directory=self.config["files"]["output_dir"]
            )
            self.webapp.run()

    def start_live(self):
        self.initialize_common_components("live")

        # Initialize interfaces (MQTT and serial) and communicator
        interfaces = {}
        interfaces[SerialInterface] = self.config["serial"]
        interfaces[MQTTInterface] = self.config["mqtt"]

        self.communicator = Communicator(interfaces=interfaces)
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

                               
# CLI
class MothicsCLI(Cmd):
    prompt = '\033[1;32m(mothics) \033[0m'
    intro = """
    ==============================================
    \033[1;36mMothics - Moth Analytics\033[0m
    Iacopo Ricci - Audace Sailing Team - 2025
    
    \033[2mDefault SSH address: \t 192.168.42.1
    Default dashboard address: \t 192.168.42.1:5000
    Type "help" for available commands.
    Type "exit" or <CTRL-D> to quit.\033[0m
    ==============================================
    """
    system_manager = SystemManager()

    def _confirm_action(self, action):
        """Prompt the user for confirmation before executing shutdown or reboot."""
        response = input(f"\033[93m[WARNING]\033[0m Are you sure you want to {action}? [Y/n]: ").strip().lower()
        return response in ["y", "yes", ""]
    
    def print(self, message, level="info"):
        """
        Prints messages with standardized formatting.
        
        level can be: "info", "warning", "error", "success", "update"
        """
        colors = {
            "info": "\033[94m[INFO]\033[0m",  # Blue
            "warning": "\033[93m[WARNING]\033[0m",  # Yellow
            "error": "\033[91m[ERROR]\033[0m",  # Red
            "success": "\033[92m[SUCCESS]\033[0m",  # Green
            "update": "\033[96m[UPDATE]\033[0m",  # Cyan
        }
        print(f"{colors.get(level, '[INFO]')} {message}")

    
    def preloop(self):
        # Check for updates before entering the CLI loop
        # Skip if no internet
        if not check_internet_connectivity():
            self.print("No internet connection. Skipping update check.", level='warning')
            return

        try:
            # Ensure we are inside a Git repository
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Get the list of remotes
            remotes = subprocess.check_output(["git", "remote"]).decode("utf-8").strip().split("\n")
            if not remotes:
                self.print("No remote repository found. Skipping update check.", level='error')
                return

            # Use the first available remote instead of assuming "origin"
            remote_name = remotes[0]

            # Fetch latest changes from the detected remote
            subprocess.run(["git", "fetch", remote_name], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Detect the default branch dynamically
            try:
                branch = subprocess.check_output(
                    ["git", "symbolic-ref", f"refs/remotes/{remote_name}/HEAD"],
                    stderr=subprocess.DEVNULL
                ).decode("utf-8").strip().split("/")[-1]
            except subprocess.CalledProcessError:
                # Fallback: Check if main exists, otherwise use master
                branch = "main" if f"{remote_name}/main" in subprocess.getoutput("git branch -r") else "master"
                
            # Get the latest commit on the remote branch
            remote_commit = subprocess.check_output(["git", "rev-parse", f"{remote_name}/{branch}"]).decode("utf-8").strip()

            # Get the current local commit
            local_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
            
            # Compare commits
            if local_commit != remote_commit:
                self.print("A new version is available! Run \033[2mupdate\033[0m or \033[2mgit pull\033[0m after exiting Mothics", level='update')
                        
        except subprocess.CalledProcessError as e:
            self.print(f"Unable to check for updates: {e}", level='error')
                
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
            self.print("Please specify a mode: live, replay or database", level='warning')
            return

        mode = parts[0].lower()
        if mode == "live":
            self.system_manager.start_live()
        elif mode == "replay":            
            # Start database
            if not self.system_manager.database:
                self.system_manager.initialize_database()

            if len(parts) <= 1:
                self.print("Please specify a track filename", level='warning')
                print("Available tracks:")
                self.do_list_tracks(args)
                return
                
            # Handle indices
            fname = tipify(parts[1])
            track_file = self.system_manager.database.get_track_path(fname)
            self.system_manager.start_replay(track_file=track_file)
        elif mode == "database":
            self.system_manager.initialize_database()
        else:
            self.print("Invalid mode. Please choose 'live' or 'replay'.", level='error')

    def do_stop(self, args):
        """Stop the running system."""
        self.system_manager.stop()

    def do_restart(self, args):
        """
        Restart the system.
        
        Usage:
            restart
            restart reload_config
        """
        parts = args.split()
        reload_config = "reload_config" in parts

        self.system_manager.restart(reload_config=reload_config)

    def do_status(self, args):
        """Display the current system status with color-coded output."""
        status = self.system_manager.get_status()

        if not status:
            self.print("No status data available.", level='warning')
            return

        # Define ANSI color codes
        color_map = {
            "stopped": "\033[91m",       # Red
            "running": "\033[92m",       # Green
            "active": "\033[92m",        # Green
            "not active": "\033[91m",    # Red
            "available": "\033[92m",     # Green
            "not initialized": "\033[91m", # Red
            "live": "",                   # No color change
            "replay": ""                   # No color change
        }
        reset_color = "\033[0m"

        # Apply color mapping
        status_table = [
            [key, f"{color_map.get(value, '')}{value}{reset_color}"] for key, value in status.items()
        ]

        # Print the table
        print(tabulate(status_table, headers=["Component", "Status"], tablefmt="github"))
        print()

    def do_list_tracks(self, args):
        """List tracks from Database"""
        if not self.system_manager.database:
            self.system_manager.initialize_database()
        self.system_manager.database.list_tracks()

    def do_select_track(self, args):
        """
        Select a track by index and display its metadata.
        """
        parts = args.split()
        if not parts:
            self.print("Please specify a track index", level='warning')
            return
        
        index = tipify(parts[0])

        if not isinstance(index, int):
            print("Please specify a track index")
            return
        
        if self.system_manager.database:
            track_meta = self.system_manager.database.select_track(index)
            if track_meta:
                self.print("Selected track metadata:", level='info')
                for key, value in track_meta.items():
                    print(f"{key}: {value}")
        else:
            self.print("Database not initialized.", level='error')

    def do_log(self, args):
        """
        Display or delete logs from the log file.
        Usage:
            log show
            log clear
        """        
        log_file = str(self.system_manager.config["files"]["logger_fname"])

        parts = args.split()
        if not parts:
            self.print("Please specify a mode: show or clear", level='warning')
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
                self.print("Log file not found.", level='error')

    def _get_system_resources(self):
        """Gather system-wide resource usage."""
        system_cpu = psutil.cpu_percent(interval=0.1)
        system_memory = psutil.virtual_memory()
        system_swap = psutil.swap_memory()
        system_disk = psutil.disk_usage('/')
        system_processes = len(psutil.pids())

        data = [
            ["CPU usage", f"{system_cpu:.2f} %"],
            ["Memory usage", f"{system_memory.used / 1024 ** 2:.2f} MB / {system_memory.total / 1024 ** 2:.2f} MB"],
            ["Swap usage", f"{system_swap.used / 1024 ** 2:.2f} MB / {system_swap.total / 1024 ** 2:.2f} MB"],
            ["Disk usage", f"{system_disk.used / 1024 ** 2:.2f} GB / {system_disk.total / 1024 ** 2:.2f} GB"],
            ["Running processes", system_processes],
        ]

        # Fetch CPU temperature (if available)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if name in ['coretemp', 'cpu_thermal']:
                        avg_temp = sum(e.current for e in entries) / len(entries)
                        data.append([f"CPU avg temp ({name})", f"{avg_temp:.1f}°C"])
        except AttributeError:
            data.append(["CPU temperature", "not available"])

        return data

    def _get_cli_resources(self):
        """Gather CLI-specific resource usage."""
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        cpu_usage = process.cpu_percent(interval=0.1)

        return [
            ["CPU usage", f"{cpu_usage:.2f} %"],
            ["Memory (RSS)", f"{mem_info.rss / 1024 ** 2:.2f} MB"],
            ["Open file descriptors", len(process.open_files())],
            ["Thread count", process.num_threads()]
        ]
                
    def do_resources(self, args):
        """
        Show resource usage, with an optional monitor mode.

        Usage:
            resources mothics       - Show only CLI process resource usage.
            resources system        - Show system-wide resource usage.
            resources               - Show both.
            resources watch         - Continuously (every 2s) update system & CLI resource usage.
            resources system watch  - Monitor only system usage.
            resources mothics watch - Monitor only CLI usage.
        
        Exit watch mode with CTRL-C.
        """
        parts = args.strip().split()
        mode = "both"
        monitor = False

        # Determine mode and whether monitoring is enabled
        if len(parts) == 1:
            if parts[0] == "watch":
                monitor = True
            else:
                mode = parts[0]
        elif len(parts) == 2 and parts[1] == "watch":
            mode = parts[0]
            monitor = True

        # Validate mode
        if mode not in ["mothics", "system", "both"]:
            self.print("Invalid option. Use 'resources mothics', 'resources system', or 'resources'.", level='error')
            return

        def display_resources():
            """Display resource usage based on selected mode."""
            output = []

            if mode in ["mothics", "both"]:
                output.append("\n\033[94mMothics CLI\033[0m")
                output.append(tabulate(self._get_cli_resources(), headers=["Resource", "Usage"], tablefmt="github"))

            if mode in ["system", "both"]:
                output.append("\n\033[94mSystem\033[0m")
                output.append(tabulate(self._get_system_resources(), headers=["Resource", "Usage"], tablefmt="github"))

            return "\n".join(output) + "\n"

        if monitor:
            try:
                while True:
                    # Clear the terminal screen
                    shutil.get_terminal_size()
                    print("\033[H\033[J", end="")

                    # Print updated resources
                    print(display_resources())

                    time.sleep(2)
            except KeyboardInterrupt:
                self.print("Monitoring stopped.", level="warning")
                return
        else:
            # Single-time execution
            print(display_resources())
                        
    def do_shell(self, args):
        """Execute shell commands without exiting the CLI.
        
        Usage:
            shell <command>
            !<command>  (shortcut)
        """
        if not args:
            self.print("Please provide a shell command.", level='warning')
            return

        try:
            result = subprocess.run(args, shell=True, text=True, capture_output=True)
            print(result.stdout)  # Print command output
            if result.stderr:
                self.print(result.stderr, level='error')
        except Exception as e:
            self.print(f"Error executing command: {e}", level='error')

    def default(self, line):
        """Allows using '!' as a shortcut to run shell commands."""
        if line.startswith("!"):
            self.do_shell(line[1:])
        else:
            self.print(f"Unknown command: {line}", level='error')
        
    def do_exit(self, args):
        """Exit the CLI stopping processes."""
        self.print("Exiting CLI.", level='info')
        try:
            self.do_stop(args)
            return True
        except:
            return False
        
    def do_kill(self, args):
        """Exit the CLI abruptly."""
        self.print("Exiting CLI abruptly.", level='info')
        return True
    
    def do_EOF(self, args):
        """Exit on Ctrl-D (EOF)."""
        self.print("Exiting CLI.", level='info')
        try:
            self.do_stop(args)
            return True
        except:
            return False
        
    def do_interface_refresh(self, args):
        """
        Refresh the communicator (re-connect new or disconnected interfaces).
        Usage:
            refresh
            refresh force
        If 'force' is specified, all interfaces will be disconnected and then reconnected.
        """
        if not self.system_manager.communicator:
            self.print("Communicator not initialized, nothing to refresh.", level='error')
            return

        force = False
        parts = args.split()
        if parts and parts[0].lower() == "force":
            force = True
        try:
            self.system_manager.communicator.refresh(force_reconnect=force)
        except Exception as e:
            self.print(f"error refreshing communicator: {e}", level='error')

    def do_update(self, args):
        """Update the CLI by pulling the latest changes from Git."""
        try:
            subprocess.run(["git", "pull"], check=True)
            self.print("Update complete: restart the CLI to apply changes.", level='info')
        except subprocess.CalledProcessError:
            self.print("Update failed. Check your Git settings or internet connection.", level='error')

    def do_shutdown(self, args):
        """Safely shuts down the system with user confirmation."""
        if not self._confirm_action("shut down the system"):
            self.print("Shutdown canceled.", level='warning')
            return

        self.system_manager.stop()
        self.print("Shutting down the system.", level='info')

        try:
            if sys.platform.startswith("linux") or sys.platform == "darwin":
                os.system("sudo shutdown now")
            elif sys.platform == "win32":
                os.system("shutdown /s /t 0")
            else:
                self.print("Shutdown command not supported on this OS.", level='error')
        except Exception as e:
            self.print(f"Unable to shutdown: {e}", level='error')

    def do_reboot(self, args):
        """Safely reboots the system with user confirmation."""
        if not self._confirm_action("reboot the system"):
            self.print("Reboot canceled.", level='warning')
            return

        self.system_manager.stop()
        self.print("Rebooting the system.", level='info')

        try:
            if sys.platform.startswith("linux") or sys.platform == "darwin":
                os.system("sudo reboot")
            elif sys.platform == "win32":
                os.system("shutdown /r /t 0")
            else:
                self.print("Reboot command not supported on this OS.", level='error')
        except Exception as e:
            self.print(f"Unable to reboot: {e}", level='error')
            
            
if __name__ == '__main__':
    cli = MothicsCLI()
    if len(sys.argv) > 1:
        # Execute the command passed as argument
        command = " ".join(sys.argv[1:])
        cli.onecmd(command)
    # Now drop into the interactive CLI
    cli.cmdloop()
