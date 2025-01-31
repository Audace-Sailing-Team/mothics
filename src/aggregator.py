import os
import numpy as np
import time
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from typing import Dict
import random

from .database import DataPoint, Track
from .helpers import tipify


class Aggregator:
    def __init__(self, raw_data=None, raw_data_getter=None, interval=5, database=None, checkpoint=30, output_dir=None):
        # Raw data
        self.raw_data = raw_data
        self.get_raw_data = raw_data_getter
        self.last_comm_time = {}
        if self.raw_data is None and self.get_raw_data is None:
            self.logger.critical(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')
            raise RuntimeError(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')

        # Thresholds (in seconds)
        self.checkpoint = checkpoint
        self.interval = interval
        """Sampling interval of the input data"""

        # Database
        self.database = database
        if database is None:
            self.database = Track()
        self.running = False

        # Directories
        self.output_dir = output_dir
        if self.output_dir is None:
            self.output_dir = 'data'
            
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, 'chk'), exist_ok=True)

        # Timers
        self.last_checkpoint = None
        
        # Setup logger
        self.logger = logging.getLogger("Aggregator")
        self.logger.info("-------------Aggregator-------------")
        
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

            # Check if no new data has been gathered within the checkpoint threshold
            if self.checkpoint is not None:
                if self.last_checkpoint is None or (timestamp - self.last_checkpoint).total_seconds() > self.checkpoint:
                    self.last_checkpoint = timestamp
                    checkpoint_fname = os.path.join(self.output_dir, f'chk/{self.last_checkpoint.strftime("%Y%m%d-%H%M%S")}.json.chk')
                    self.logger.info(f"saving checkpoint to JSON: {checkpoint_fname}")
                    self.database.export_to_json(checkpoint_fname)

            
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
