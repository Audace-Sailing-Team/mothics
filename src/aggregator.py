import numpy as np
import time
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict
import random

from .database import DataPoint, Database
from .helpers import tipify


class Aggregator:
    def __init__(self, raw_data=None, raw_data_getter=None, interval=5, database=None):
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
        
        # Setup logger
        self.logger = logging.getLogger("Aggregator")
        self.logger.info("-------------Aggregator-------------")

    def _format_topic(self, topic):
        """
        Split MQTT topic in its components.  
        MQTT topics are composed by <module>/<sensor>/<quantity>/
        """
        topic_split = topic.split("/")
        assert len(topic_split) == 3, "topic is malformed, got {topic_split}"
        return topic_split
            
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
            
            # Add to database as a DataPoint
            assert self.database is not None, 'error initializing Database'
            self.database.add_point(timestamp, flat_data)
            
        except Exception as e:
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
