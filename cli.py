#!/usr/bin/env python3
import threading
import glob
import serial
import psutil
import argh
import logging
import os
import time
import sys
import shutil
import subprocess
from tabulate import tabulate
from cmd import Cmd
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from mothics.helpers import setup_logger, tipify, check_internet_connectivity
from mothics.system_manager import SystemManager

                               
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

    def __init__(self):
        super().__init__()
        self.serial_threads = []
        self.keep_streaming = False
        self.available_ports = []
    
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

    def _check_updates(self):
        """Check for updates"""
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

            # Use the first available remote
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
                self.print("A new version is available! Run \033[2mupdate\033[0m now or \033[2mgit pull\033[0m after exiting Mothics", level='update')
                        
        except subprocess.CalledProcessError as e:
            self.print(f"Unable to check for updates: {e}", level='error')
            return
        
    def preloop(self):
        self._check_updates()

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

    # def _get_system_resources(self):
    #     """Gather system-wide resource usage."""
    #     system_cpu = psutil.cpu_percent(interval=0.1)
    #     system_memory = psutil.virtual_memory()
    #     system_swap = psutil.swap_memory()
    #     system_disk = psutil.disk_usage('/')
    #     system_processes = len(psutil.pids())

    #     data = [
    #         ["CPU usage", f"{system_cpu:.2f} %"],
    #         ["Memory usage", f"{system_memory.used / 1024 ** 2:.2f} MB / {system_memory.total / 1024 ** 2:.2f} MB"],
    #         ["Swap usage", f"{system_swap.used / 1024 ** 2:.2f} MB / {system_swap.total / 1024 ** 2:.2f} MB"],
    #         ["Disk usage", f"{system_disk.used / 1024 ** 2:.2f} GB / {system_disk.total / 1024 ** 2:.2f} GB"],
    #         ["Running processes", system_processes],
    #     ]

    #     # Fetch CPU temperature (if available)
    #     try:
    #         temps = psutil.sensors_temperatures()
    #         if temps:
    #             for name, entries in temps.items():
    #                 if name in ['coretemp', 'cpu_thermal']:
    #                     avg_temp = sum(e.current for e in entries) / len(entries)
    #                     data.append([f"CPU avg temp ({name})", f"{avg_temp:.1f}°C"])
    #     except AttributeError:
    #         data.append(["CPU temperature", "not available"])

    #     return data

    def _get_system_resources(self):
        """Gather system-wide resource usage, including get_throttled status."""
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

        # Fetch get_throttled status
        throttled_flags, throttled_messages = self._get_throttled_status()
        data.extend([["Throttling", hex(throttled_flags)+' - '+msg] for msg in throttled_messages])

        return data

    def _get_throttled_status(self):
        """Runs 'vcgencmd get_throttled' and returns the raw and translated status."""
        try:
            result = subprocess.run(["sudo", "vcgencmd", "get_throttled"], capture_output=True, text=True, check=True)
            raw_value = result.stdout.strip().split("=")[-1]
            throttled_flags = int(raw_value, 16)  # Convert hex to int
            return throttled_flags, self._translate_throttled_flags(throttled_flags)
        except Exception as e:
            self.print(f"Error checking get_throttled: {e}", level='error')
            return 0, ["Could not retrieve throttling status"]

    def _translate_throttled_flags(self, flags):
        """Translates the get_throttled hex value into human-readable messages."""
        issues = []
        mapping = {
            0x1: "Under-voltage detected",
            0x2: "ARM frequency capped",
            0x4: "Currently throttled",
            0x8: "Soft temperature limit active",
            0x10000: "Under-voltage has occurred",
            0x20000: "ARM frequency cap has occurred",
            0x40000: "Throttling has occurred",
            0x80000: "Soft temperature limit has occurred"
        }

        for bitmask, message in mapping.items():
            if flags & bitmask:
                issues.append(message)

        return issues if issues else ["No throttling detected"]
    
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

    def do_serial(self, args):
        """
        Manage serial connections.
        
        Usage:
            serial list                - List available serial ports
            serial stream <index>      - Stream data from a selected port
            serial stop                - Stop the active serial stream
        """
        parts = args.split()
        if not parts:
            self.print("Please specify a command: list, stream, or stop", level='warning')
            return

        command = parts[0].lower()
        if command == "list":
            self._list_serial_ports()
        elif command == "stream":
            if len(parts) < 2:
                self.print("Specify an index or use 'all' to stream from all ports.", level='warning')
                return
            self._start_serial_stream(parts[1])
        elif command == "stop":
            self._stop_serial_stream()
        else:
            self.print("Unknown serial command.", level='error')

    def _list_serial_ports(self):
        """Lists available serial devices with indexing."""
        serial_ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
        if not serial_ports:
            self.print("No serial devices found.", level='warning')
            return
        
        self.available_ports = serial_ports
        self.print("Available serial devices:", level='info')
        for idx, port in enumerate(serial_ports, start=1):
            print(f" {idx}: {port}")

    def _start_serial_stream(self, selection):
        """Starts streaming from a selected port or all ports."""
        if not self.available_ports:
            self.print("No serial ports found. Run 'serial list' first.", level='error')
            return

        self.keep_streaming = True

        if selection.lower() == "all":
            ports = self.available_ports
        else:
            try:
                index = int(selection) - 1
                if index < 0 or index >= len(self.available_ports):
                    self.print("Invalid index. Use 'serial list' to see available ports.", level='error')
                    return
                ports = [self.available_ports[index]]
            except ValueError:
                self.print("Invalid input. Please provide a valid index or 'all'.", level='error')
                return

        def read_serial(port):
            """Reads data from a specific serial port."""
            baudrate = 9600  # Default baudrate, adjust if necessary
            try:
                with serial.Serial(port, baudrate=baudrate, timeout=1) as ser:
                    self.print(f"Streaming from {port}... Press CTRL-C to stop.", level='info')
                    while self.keep_streaming:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                        if line:
                            print(f"[{port}] {line}")
            except serial.SerialException as e:
                self.print(f"Error reading from {port}: {e}", level='error')

        # Start a thread for each port
        for port in ports:
            thread = threading.Thread(target=read_serial, args=(port,), daemon=True)
            self.serial_threads.append(thread)
            thread.start()

    def _stop_serial_stream(self):
        """Stops all active serial streams."""
        if not self.keep_streaming:
            self.print("No active serial stream to stop.", level='warning')
            return
        
        self.keep_streaming = False
        self.print("Stopping serial streams...", level='info')

        for thread in self.serial_threads:
            thread.join(timeout=2)

        self.serial_threads = []  # Clear threads list

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

    def do_detach(self, args):
        """
        Detach from the current tmux session without killing it.

        Usage:
            detach
        """
        try:
            subprocess.run(["tmux", "detach-client"], check=True)
            self.print("Detached from tmux session. You can reattach using 'tmux attach'.", level='info')
        except subprocess.CalledProcessError as e:
            self.print(f"Error detaching from tmux: {e}", level='error')        

    def do_update(self, args):
        """Update the CLI by pulling the latest changes from Git."""
        # Check for updates
        self._check_updates()
        
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
    # Drop into the interactive CLI
    cli.cmdloop()
