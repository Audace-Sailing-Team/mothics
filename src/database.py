from tabulate import tabulate
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import csv
import json
import logging

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


@dataclass
class Track:
    data_points: List[DataPoint] = field(default_factory=list)
    field_names: Optional[List[str]] = None
    mode: Optional[str] = 'live'
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("Track"))
    _replay_index: int = 0  # Internal index for replay mode
    
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

    def add_point(self, timestamp: datetime, data: Dict[str, Any]):
        """Add a data point ensuring field consistency."""
        # Validate or establish field consistency
        # NOTE: if no field names are passed, no checks are performed
        if self.field_names is not None and set(self.field_names) != set(data.keys()):
            raise ValueError(f"Inconsistent fields. Expected {self.field_names}, got {list(data.keys())}")
            
        self.data_points.append(DataPoint(timestamp, data))

    def export_to_csv(self, filename: str):
        """Exports the database to a CSV file."""
        if not self.data_points:
            raise ValueError("No data points to export")

        with open(filename, mode='w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['timestamp'] + self.field_names)
            writer.writeheader()
            for point in self.data_points:
                row = {'timestamp': point.timestamp.isoformat(), **point.data}
                writer.writerow(row)

    def export_to_json(self, filename: str):
        """Exports the database to a JSON file."""
        with open(filename, mode='w') as jsonfile:
            json.dump([asdict(dp) for dp in self.data_points], jsonfile, default=str, indent=4)

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

    def get_latest_data(self) -> List[DataPoint]:
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


            
