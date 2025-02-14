import glob
import os
import csv
import json
import logging
from tabulate import tabulate
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


@dataclass
class DataPoint:
    timestamp: datetime
    input_data: Dict[str, Any]

    def __post_init__(self):
        """Verify and check data"""        
        # Check input data validity
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime object")
        if not isinstance(self.input_data, dict):
            raise ValueError("data must be a dictionary")
        
    def to_dict(self):
        """
        Export the data point as a dictionary including the timestamp and input data.
        Returns:
            A dictionary with 'timestamp' and 'data'.
        """
        return {"timestamp": self.timestamp.isoformat()} | self.input_data


class Track:
    def __init__(self,
                 data_points: Optional[List[DataPoint]] = None,
                 field_names: Optional[List[str]] = None,
                 mode: Optional[str] = 'live',
                 save_mode: Optional[str] = 'continuous',
                 checkpoint_interval: Optional[int] = 30,
                 max_checkpoint_files: Optional[int] = 3,
                 output_dir: Optional[str] = None):
        # Initialize the fields with defaults
        self.data_points = data_points if data_points is not None else []
        self.field_names = field_names
        self.mode = mode
        self.save_mode = save_mode
        self.checkpoint_interval = checkpoint_interval
        self.max_checkpoint_files = max_checkpoint_files
        self.output_dir = output_dir if output_dir is not None else 'data'
        
        # Internal attributes not exposed as parameters
        self._replay_index = 0
        self._last_checkpoint = None
        self._save_interval_start = None
        
        # Setup directories for output and checkpoints
        self.checkpoint_dir = os.path.join(self.output_dir, 'chk')
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.checkpoint_dir, exist_ok=True)

        # Setup logger
        self.logger = logging.getLogger("Track")
        self.logger.info("-------------Track-------------")
        self.logger.info(f'output directory: {self.output_dir}')
        self.logger.info(f'checkpoint directory: {self.checkpoint_dir}')
        
    def __str__(self):
        """Returns a tabular view of all data points."""
        if not self.data_points:
            return "No data points available."
        
        # Set available field names if None are provided 
        if self.field_names is None:
            self.field_names = list(self.data_points[-1].to_dict().keys())
        
        # Prepare headers and rows for the table
        headers = ["Timestamp"] + self.field_names
        rows = [[dp.timestamp.isoformat()] + [dp.input_data.get(field, "") for field in self.field_names] for dp in self.data_points]

        return tabulate(rows, headers=headers, tablefmt="github")

    def load(self, filename: str):
        """Loads a Track object from a JSON file."""
        with open(filename, 'r') as f:
            try:
                data = json.load(f)
            except:
                self.logger.critical(f'could not load {filename} into a Track')
                raise RuntimeError(f'could not load {filename} into a Track')

        self.data_points = [DataPoint(datetime.fromisoformat(dp["timestamp"]), dp["input_data"]) for dp in data]
        self.mode = 'replay'

    def save(self, format='json', fname=None, interval=None):
        """Save track on JSON or CSV file""" 
        if fname is None:
            fname = os.path.join(self.output_dir, f'{datetime.now().strftime("%Y%m%d-%H%M%S")}')
        try:
            if format == 'csv':
                fname += '.csv'
                self.export_to_csv(fname, interval=interval)
                self.logger.info(f"saving track to CSV: {fname}")
            else:
                fname += '.json'
                self.export_to_json(fname, interval=interval)
                self.logger.info(f"saving track to JSON: {fname}")
        except Exception as e:
            self.logger.critical(f'error in saving track: {e}')

    def start_run(self):
        """Start a sampling run"""
        if self.save_mode == 'on-demand':
            self.save_mode = 'continuous'
            # Save index of first frame to be saved
            self._save_interval_start = len(self.data_points) - 1
            self.logger.info('logging data')
        elif self.save_mode == 'continuous':
            self.logger.warning(f'cannot start track saving on demand; current saving mode is {self.save_mode}')
        
    def end_run(self):
        """End a sampling run"""
        if self.save_mode != 'on-demand': # FLAWED current save status check
            # Generate slice and save track
            interval = slice(self._save_interval_start, len(self.data_points) - 1)
            self.save(interval=interval)
            # Cleanup checkpoint storage
            chk_files = os.listdir(self.checkpoint_dir)
            for f in chk_files:
                os.remove(os.path.join(self.checkpoint_dir, f))
            # Clean up interval indices and reset mode
            self._save_interval_start = None
            self._last_checkpoint = None
            self.save_mode = 'on-demand'
            self.logger.info('data logging ended')
        else:
            self.logger.warning(f'cannot end track saving; current saving mode is {self.save_mode}')
    
    def _save_checkpoint(self):
        """Save a checkpoint after a certain amount of seconds"""
        if self.save_mode == 'continuous' and self.checkpoint_interval is not None:
            now = datetime.now()
            # Save a checkpoint if above time threshold (or no points are available)
            if self._last_checkpoint is None or (now - self._last_checkpoint).total_seconds() > self.checkpoint_interval:
                self._last_checkpoint = now
                interval = slice(self._save_interval_start, len(self.data_points) - 1)
                self.save(interval=interval, fname=os.path.join(self.checkpoint_dir, f'{now.strftime("%Y%m%d-%H%M%S")}.chk'))

            # Remove older files from checkpoint directory
            if len(os.listdir(self.checkpoint_dir)) > self.max_checkpoint_files:
                chk_files = glob.glob(os.path.join(self.checkpoint_dir, "*.chk.json"))
                chk_files.sort(key=os.path.getmtime)
                # Delete the oldest file
                os.remove(chk_files[0])

    def export_to_json(self, filename, interval=None):
        """Exports the database to a JSON file."""
        # Slice data_point list
        data_points_to_export = self.data_points
        if interval is not None:
            data_points_to_export = self.data_points[interval]

        with open(filename, mode='w') as jsonfile:
            json.dump([asdict(dp) for dp in data_points_to_export], jsonfile, default=str, indent=4)

    def export_to_csv(self, filename, interval=None):
        """Exports the database to a CSV file."""
        if not self.data_points:
            self.logger.critical("no data points to export.")
            raise ValueError("no data points to export.")

        # Slice data_point list
        data_points_to_export = self.data_points
        if interval is not None:
            data_points_to_export = self.data_points[interval]

        with open(filename, mode='w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['timestamp'] + self.field_names)
            writer.writeheader()
            for point in data_points_to_export:
                row = {'timestamp': point.timestamp.isoformat(), **point.data}
                writer.writerow(row)

    def add_point(self, timestamp: datetime, data: Dict[str, Any]):
        """Add a data point ensuring field consistency."""
        # Validate or establish field consistency
        # NOTE: if no field names are passed, no checks are performed
        if self.field_names is not None and set(self.field_names) != set(data.keys()):
            raise ValueError(f"Inconsistent fields. Expected {self.field_names}, got {list(data.keys())}")
            
        self.data_points.append(DataPoint(timestamp, data))
        # Run checkpointing
        self._save_checkpoint()

    def get_latest_data(self):
        """Returns the latest data point for each unique entry."""
        if not self.data_points:
            return []

        latest_data = {}
        for dp in self.data_points:
            for field, value in dp.data.items():
                latest_data[field] = dp  # Overwrite to get the most recent

        return list(latest_data.values())

    def get_current(self):
        """Returns the current Track instance."""
        if self.mode == "live":
            return self  # In live mode, return the latest track
        elif self.mode == "replay":
            return self._get_replay_track()

    def _get_replay_track(self):
        """Returns a progressively growing Track instance in replay mode."""
        if not self.data_points:
            raise ValueError("No data available for replay")

        # Limit replay index
        self._replay_index = min(self._replay_index + 1, len(self.data_points))

        # Create a new track with data up to the current replay index
        mock_track = Track()
        mock_track.field_names = self.field_names
        mock_track.data_points = self.data_points[:self._replay_index]

        return mock_track
