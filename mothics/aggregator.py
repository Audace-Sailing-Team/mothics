import glob
import os
import time
import logging
import threading
from datetime import datetime, timedelta
from traceback import format_exc

from .track import DataPoint, Track
from .helpers import tipify


class Aggregator:
    def __init__(self, raw_data=None, raw_data_getter=None, interval=5, database=None, output_dir=None):
        self.running = False
        """Aggregator loop status"""
        # Raw data
        self.raw_data = raw_data
        self.get_raw_data = raw_data_getter
        self.last_comm_time = {}
        if self.raw_data is None and self.get_raw_data is None:
            self.logger.critical(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')
            raise RuntimeError(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')

        # Thresholds (in seconds)
        self.interval = interval
        """Sampling interval of the input data"""

        # Database
        self.database = database
        if database is None:
            self.database = Track(output_dir=output_dir)
            
        # Setup logger
        self.logger = logging.getLogger("Aggregator")
        self.logger.info("-------------Aggregator-------------")
                            
    def aggregate(self):
        """Fetch raw data and store it as a DataPoint in a Track."""
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
                # Get topic for timestamp
                last_timestamp_id = topic.split('/')[0] + '/last_timestamp'
                try:
                    flat_data[topic] = list(value[-1].values())[0]
                    
                    # Get timestamp from raw_data for each topic
                    # NOTE: for simplicity, this just overwrites the
                    # last fetched timestamp, not caring about
                    # differences in timestamps from different sensors
                    # in the same unit
                    flat_data[last_timestamp_id] = list(value[-1].keys())[0]
                except IndexError:
                    flat_data[topic] = None
                    flat_data[last_timestamp_id] = None
            
            # Add to database as a DataPoint
            assert self.database is not None, 'error initializing Database'
            self.database.add_point(timestamp, flat_data)
            
        except Exception as e:
            self.logger.critical(f"error during aggregation: {e} \n {format_exc()}")
            
    def start(self):
        """Start the loop in non-blocking mode."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name='Aggregator loop')
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
