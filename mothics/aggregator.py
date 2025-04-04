"""
Aggregator
==========

This module provides the `Aggregator` class, which periodically
collects and aggregates incoming data from one or more sources, then
stores or processes it for later use. Typical usage is to instantiate
an `Aggregator` with a raw-data reference (or preferably a callable
returning it), and then call `start()` to run the collection loop in a
separate thread.

Classes
-------
- Aggregator: Manages recurring data retrieval and appends it to a `Track` database.

Dependencies
------------
- Local imports from the same package:
  - `.track` (contains `DataPoint`, `Track`)
  - `.helpers` (provides `tipify`)
  
Notes
-----
- The aggregator internally maintains a reference to a `Track` object (`self.database`), 
  which is where aggregated data points are ultimately stored.
- If no `Track` is explicitly provided, a default one is created automatically, 
  optionally storing output in a specified directory.

"""

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
    """
    Periodically collects data from a provided source and stores it in a `Track`.

    The `Aggregator` can operate in a continuous loop (via `start()`/`stop()`)
    or be called manually with `aggregate()` to control the timing yourself.
    """
    
    def __init__(self, raw_data=None, raw_data_getter=None, interval=1, database=None, output_dir=None):
        """
        Initialize the aggregator.

        Args:
            raw_data (dict, optional): An existing dictionary for reading new data
                (e.g., shared by other processes). If `raw_data_getter` is None,
                this dictionary must be valid. Defaults to None.
            raw_data_getter (callable, optional): A function that returns the
                current data dictionary. If both `raw_data` and `raw_data_getter`
                are provided, `raw_data_getter` is used. Defaults to None.
            interval (float, optional): The time interval (in seconds) at which
                the aggregator will collect data when running in looped mode.
                Defaults to 1.
            database (Track, optional): A `Track` instance to store data. If None,
                a new `Track` object is instantiated. Defaults to None.
            output_dir (str, optional): If no `database` is provided, a new one is
                created with `output_dir` as its storage location. Defaults to None.

        Raises:
            RuntimeError: If neither `raw_data` nor `raw_data_getter` is provided.
        """
        
        self.running = False
        """Aggregator loop status"""
        # Raw data management
        self.raw_data = raw_data
        """Dictionary containing raw data to be aggregated"""
        self.get_raw_data = raw_data_getter
        """External getter function to fetch a raw data dictionary"""
        self.last_comm_time = {}
        """Last timestamp from all managed topics"""
        # Handle raw_data
        if self.raw_data is None and self.get_raw_data is None:
            self.logger.critical(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')
            raise RuntimeError(f'no raw data nor getter available, got {raw_data=}, {raw_data_getter=}')

        # Thresholds (in seconds)
        self.interval = interval
        """Sampling interval of the input data"""

        # Track
        # TODO: rename to "track" for consistency
        self.database = database
        """Track instance to store data"""
        if database is None:
            self.database = Track(output_dir=output_dir)
            
        # Setup logger
        self.logger = logging.getLogger("Aggregator")
        self.logger.info("-------------Aggregator-------------")
                            
    def aggregate(self):
        """
        Fetch raw data and store it as a `DataPoint` in the aggregator's `Track`.

        This method:
          1. acquires the latest data from `get_raw_data` if available; otherwise
             uses `self.raw_data`
          2. extracts the newest value for each topic (and the associated timestamp)
          3. creates a new data point in the `database` with the current system time
             and the flattened data dictionary.

        Exceptions are caught and logged; a critical error log is generated if
        data collection or insertion fails.
        """
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
        """
        Begin collecting data at regular intervals in a background thread.

        Once this method is called, the `Aggregator` spawns a new thread that
        invokes `aggregate()` every `self.interval` seconds. To stop it, call
        `stop()`.
        """
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True, name='Aggregator loop')
            self.thread.start()
            self.logger.info("started non-blocking loop.")

    def _run_loop(self):
        """
        Internal loop for the aggregator.

        This loop continuously calls `aggregate()` then sleeps for `self.interval`
        seconds. It remains active while `running` is True.
        """
        while self.running:
            self.aggregate()
            time.sleep(self.interval)            

    def stop(self):
        """
        Stop the aggregator loop.

        If running in non-blocking mode, this signals the background thread
        to exit and waits for it to terminate. Safely disables further data
        collection until `start()` is called again.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self.logger.info("stopped loop.")
