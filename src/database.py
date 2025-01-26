from tabulate import tabulate
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
import csv
import json


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
class Database:
    data_points: List[DataPoint] = field(default_factory=list)
    field_names: Optional[List[str]] = None  # Stores the set of consistent fields dynamically

    def add_point(self, timestamp: datetime, data: Dict[str, Any]):
        """Adds a data point and ensures field consistency."""
        # Validate or establish field consistency
        if self.field_names is None:
            self.field_names = list(data.keys())
        elif set(self.field_names) != set(data.keys()):
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

    def filter_by_time_range(self, start_time: datetime, end_time: datetime) -> List[DataPoint]:
        """Returns data points within a specific time range."""
        return [dp for dp in self.data_points if start_time <= dp.timestamp <= end_time]

    def __str__(self):
        """Returns a tabular view of all data points."""
        if not self.data_points:
            return "No data points available."

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
