import traceback
import numpy as np
import time
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from typing import Dict
import random

from .database import DataPoint, Database
from .helpers import tipify


class Aggregator:
    def __init__(self, raw_data=None, raw_data_getter=None, interval=5, database=None, status_noncomm=30, status_offline=60):
        """
        Asynchronous Aggregator class that periodically fetches raw sensor
        data and stores it in a Database.

        Parameters:
        - raw_data: unprocessed data from the Communication Interface. 
                    Data structure is
                    `{topic1: [{timestamp: value1}, ...]}`
        - raw_data_getter: getter function for raw data from comms
        - interval: Time interval (seconds) between data aggregation cycles.
        - database: Input database object; if None is provided, one is created
        """
        self.raw_data = raw_data
        self.get_raw_data = raw_data_getter
        
        if self.raw_data is None and self.get_raw_data is None:
            self.logger.critical(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')
            raise RuntimeError(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')
        
        self.interval = interval
        """Sampling interval of the input data"""

        self.database = database
        if database is None:
            self.database = Database()
        self.running = False

        # Thresholds for status (in seconds)
        self.status_noncomm = status_noncomm
        self.status_offline = status_offline

        # Setup logger
        self.logger = logging.getLogger("Aggregator")
        self.logger.info("-------------Aggregator-------------")

    @property
    def remote_status(self):
        """
        Compute status of all remote units based on raw data timestamps.

        Status levels:
        - 'online': The unit has communicated within the `status_noncomm` interval.
        - 'noncomm': The unit has not communicated within the `status_noncomm` interval.
        - 'offline': The unit has not communicated within the `status_offline` interval.

        Returns:
        - A dictionary with remote unit names as keys and their status as values.
        """
        if not self.raw_data:
            self.logger.warning("No raw data available to compute remote statuses.")
            return {}

        # Get current time
        now = datetime.now()
        status = {}

        for topic, entries in self.raw_data.items():
            # Extract remote unit name from topic
            remote_name = topic.split('/')[0]

            # No entries == rm is offline
            if not entries:
                status[remote_name] = "offline"
                continue

            # Get latest timestamp for topic
            try:
                latest_timestamp = list(entries[-1].keys())[0]  # Extract timestamp from last entry
                # latest_timestamp = datetime.fromisoformat(latest_timestamp)  # Convert to datetime
            except (IndexError, ValueError):
                self.logger.error(f"invalid data format for topic '{topic}'.")
                status[remote_name] = "offline"
                continue

            # Compare timestamps
            if now - timedelta(seconds=self.status_offline) > latest_timestamp:
                status[remote_name] = "offline"
            elif now - timedelta(seconds=self.status_noncomm) > latest_timestamp:
                status[remote_name] = "noncomm"
            else:
                status[remote_name] = "online"

        # Log
        # for remote, state in status.items():
        #     self.logger.info(f"remote '{remote}' is {state}")

        return status

    # @property
    # def remote_status(self):
    #     """
    #     Compute status of all remote units.
    #     """
    #     # Get current time
    #     now = datetime.now()

    #     # Get all topics
    #     topics = []
    #     for interface in self.interfaces.values():
    #         topics.extend(interface.topics)
    #     topics = [t for t in topics if not t.endswith('sudo')]

    #     # Get all available remote units
    #     remotes = list(set([self._format_topic(t)[0] for t in topics]))
        
    #     # Initialize statuses
    #     status = {name: 'online' for name in remotes}
        
    #     # Get available topics from each interface
    #     for interface in self.interfaces.values():
    #         for topic in interface.topics:
    #             # Get remote name
    #             remote_name = self._format_topic(topic)[0]
    #             # Avoid central unit to remote unit communication topics
    #             if self._format_topic(topic)[1] == 'sudo':
    #                 continue
    #             # Get timestamp from last point
    #             try:
    #                 last_point_timestamp = list(interface.raw_data[topic][-1].keys())[0]
    #             except IndexError:
    #                 status[remote_name] = 'offline'
    #                 continue
    #             # Set non-communicative
    #             if (now - timedelta(seconds=self.status_noncomm)) > last_point_timestamp:
    #                 status[remote_name] = 'noncomm'
    #                 self.logger.info(f'{remote_name} is non-communicative')
    #             # Set offline
    #             if (now - timedelta(seconds=self.status_offline)) > last_point_timestamp:
    #                 status[remote_name] = 'offline'
    #                 self.logger.info(f'{remote_name} is offline')
    #     # # Cleanup names
    #     # if self.thesaurus:
    #     #     return {self.thesaurus[k]: v for k, v in status.items()}
    #     # else:
    #     return status
        
    def aggregate(self):
        """Fetches raw data and stores it as a DataPoint in the Database."""
        try:
            timestamp = datetime.now()
            
            # Get data with thread lock to ensure no reading operation
            # is tampered with by outside processes
            self._lock = threading.Lock()

            if self.get_raw_data is not None:
                with self._lock:
                    self.raw_data = self.get_raw_data()

            # Flatten sensor data
            flat_data = {}
            for topic, value in self.raw_data.items():
                try:
                    flat_data[topic] = list(value[-1].values())[0]
                except IndexError:
                    # If no values are available
                    flat_data[topic] = None

            # Compute remote statuses
            statuses = self.remote_status
            
            # Combine statuses with sensor data
            for remote_name, status in statuses.items():
                status_key = f"{remote_name}/status"
                flat_data[status_key] = status
            
            # Add to database as a DataPoint
            assert self.database is not None, 'error initializing Database'
            self.database.add_point(timestamp, flat_data)
            
        except Exception as e:
            print(traceback.format_exc())
            self.logger.critical(f"error during aggregation: {e}")
            
    def start(self):
        """Start the loop in non-blocking mode."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            self.logger.info("started non-blocking loop.")

    def _run_loop(self):
        """The loop logic for non-blocking mode."""
        while self.running:
            self.aggregate()
            time.sleep(self.interval)            

    def stop(self):
        """Stop the loop, for both blocking and non-blocking modes."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self.logger.info("stopped loop.")

    def export_data(self, file_format: str = "csv", filename: str = "aggregated_data"):
        """Exports data asynchronously using the Database's export methods."""
        if file_format == "csv":
            self.database.export_to_csv_async(f"{filename}.csv")
        elif file_format == "json":
            self.database.export_to_json_async(f"{filename}.json")
        else:
            self.logger.critical("unsupported file format. Use 'csv' or 'json'.")
            raise ValueError("unsupported file format. Use 'csv' or 'json'.")
