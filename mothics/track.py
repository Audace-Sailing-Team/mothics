"""
This module defines a system to record streaming of historical
sensor data as `DataPoint` objects, contained and managed through a
`Track`, and export the results in various formats (JSON, CSV, GPX).

Classes
-------
- DataPoint:  A dataclass holding a timestamp and an associated data dictionary.
- Track:      Manages a list of `DataPoint` objects, provides replay functionality,
              and handles export operations.

Functions
---------
- export_to_json: Exports a list of `DataPoint` objects to a JSON file.
- export_to_csv:  Exports a list of `DataPoint` objects to a CSV file.
- export_to_gpx:  Exports a list of `DataPoint` objects to a GPX file
                  for geospatial data visualization (e.g., on a map).

Notes
-----
- The `DataPoint` dataclass automatically validates its timestamp and data upon instantiation.
- Export operations can slice data based on an optional `interval` parameter 
  (e.g., a Python slice object) to save only part of the dataset.
- User defined export functions can be used, as long as they follow the `_export_base` structure.

"""
import re
import glob
import os
import csv
import json
import logging
from tabulate import tabulate
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET

@dataclass
class DataPoint:
    """
    Represents a single data measurement at a given point in time.

    Attributes:
        timestamp (datetime): The exact time this data point was recorded.
        input_data (dict[str, Any]): Arbitrary key-value pairs representing sensor data.
    """
    timestamp: datetime
    input_data: Dict[str, Any]

    def __post_init__(self):
        """
        Validate the DataPoint fields after initialization.

        Raises:
            ValueError: If `timestamp` is not a datetime or `input_data` is not a dict.
        """
        # Check input data validity
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime object")
        if not isinstance(self.input_data, dict):
            raise ValueError("data must be a dictionary")
        
    def to_dict(self):
        """
        Export the data point as a dictionary, including the timestamp and input data.

        Returns:
            dict: A dictionary with keys:
                  - "timestamp": A string of the timestamp in ISO format.
                  - All key-value pairs from `input_data`.
        """
        return {"timestamp": self.timestamp.isoformat()} | self.input_data


def export_to_json(data_points, filename, interval=None, field_names=None):
    """
    Export a list of DataPoint objects to a JSON file.

    Args:
        data_points (list[DataPoint]): The data points to export.
        filename (str): Path to the JSON file.
        interval (slice, optional): If provided, only data points in this slice
            are exported. Defaults to exporting the entire list.
        field_names (list[str], optional): Not currently used by this function,
            but maintained for API compatibility.

    Raises:
        RuntimeError: If `data_points` is None or empty.
    """
    if data_points is None:
        raise RuntimeError("no data points to save.")
    
    # Slice data_point list
    data_points_to_export = data_points
    if interval is not None:
        data_points_to_export = data_points[interval]

    with open(filename, mode='w') as jsonfile:
        json.dump([asdict(dp) for dp in data_points_to_export], jsonfile, default=str, indent=4)

def export_to_csv(data_points, filename, interval=None, field_names=None):
    """
    Export a list of DataPoint objects to a CSV file.

    Args:
        data_points (list[DataPoint]): The data points to export.
        filename (str): Path to the CSV file.
        interval (slice, optional): If provided, only the indicated portion of 
            the data points list is exported.
        field_names (list[str], optional): A list of field names to include as
            columns in the CSV. If None, the function attempts to derive them 
            from the first data point's `input_data` keys.

    Raises:
        RuntimeError: If `data_points` is None or empty.
    """
    if data_points is None:
        raise RuntimeError("no data points to save.")
    
    # Slice data_point list
    data_points_to_export = data_points
    if interval is not None:
        data_points_to_export = data_points[interval]

    # Generate field names if not provided or invalid
    if not field_names:
        # NOTE: not the best way to proceed, but it works
        #       ideally, a "get_fields" method should be implemented
        #       in DataPoint
        field_names = list(data_points_to_export[0].input_data.keys())
        
    with open(filename, mode='w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['timestamp'] + field_names)
        writer.writeheader()
        for point in data_points_to_export:
            row = {'timestamp': point.timestamp.isoformat(), **point.input_data}
            writer.writerow(row)

def export_to_gpx(data_points, filename, interval=None):
    """
    Export a list of DataPoint objects to a GPX file.

    This is primarily used for geospatial data where each DataPoint's
    `input_data` contains latitude and longitude fields (e.g., "gps/lat", "gps/lon").

    Args:
        data_points (list[DataPoint]): The data points to export.
        filename (str): Path to the GPX file.
        interval (slice, optional): If provided, only that portion of `data_points`
            is exported.

    Raises:
        RuntimeError: If `data_points` is None or empty.
    """
    if data_points is None:
        raise RuntimeError("no data points to save.")
    
    # Slice data_point list
    data_points_to_export = data_points
    if interval is not None:
        data_points_to_export = data_points[interval]

    # Create the root GPX element
    gpx = ET.Element("gpx", version="1.1", creator="TrackExporter")
    
    # Metadata (creator, time, etc.)
    metadata = ET.SubElement(gpx, "metadata")
    name = ET.SubElement(metadata, "name")
    name.text = "Mothics Track export"
    desc = ET.SubElement(metadata, "desc")
    desc.text = "Exported track data generated using Mothics"
    
    # Add a track (trk)
    trk = ET.SubElement(gpx, "trk")
    trkseg = ET.SubElement(trk, "trkseg")  # Track segment

    for dp in data_points_to_export:
        # Get lat, lon keys
        lat_key = next((key for key in dp.input_data if key.endswith('lat')), None)
        lon_key = next((key for key in dp.input_data if key.endswith('lon') or key.endswith('long')), None)
        
        lat = dp.input_data.get(lat_key)
        lon = dp.input_data.get(lon_key)

        if lat is None or lon is None:
            continue
        
        trkpt = ET.SubElement(trkseg, "trkpt", lat=str(lat), lon=str(lon))

        # Optional: Add elevation if available
        alt_key = next((key for key in dp.input_data if key.endswith(('alt', 'elev', 'altitude'))), None)
        alt = dp.input_data.get(alt_key)
        if alt is not None:
            ele = ET.SubElement(trkpt, "ele")
            ele.text = str(alt)

        # Timestamp
        time = ET.SubElement(trkpt, "time")
        time.text = dp.timestamp.isoformat()  # Timestamp in ISO 8601 format

    # Write the GPX file
    tree = ET.ElementTree(gpx)
    tree.write(filename)

_export_methods = {'json': export_to_json, 'csv': export_to_csv, 'gpx': export_to_gpx}


# Track
class Track:
    """
    Stores and manages a list of DataPoint objects and provides
    replay, export, and checkpointing functionality.

    Tracks can be updated in real-time with new data points, or loaded
    from disk for review. Size of the data in memory is automatically
    limited and portions of data can be saved to disk in various
    formats.
    """
    
    def __init__(self,
                 data_points: Optional[List[DataPoint]] = None,
                 field_names: Optional[List[str]] = None,
                 mode: Optional[str] = 'live',
                 save_mode: Optional[str] = 'continuous',
                 checkpoint_interval: Optional[int] = 120,
                 max_checkpoint_files: Optional[int] = 3,
                 trim_fraction: Optional[float] = 0.5,
                 max_datapoints: Optional[int] = 1e5,
                 output_dir: Optional[str] = None):
        """
        Initialize a new Track instance.

        Args:
            data_points (list[DataPoint], optional): An initial list of data points.
            field_names (list[str], optional): Expected keys in each data point's 
                `input_data`. If set, data points with different sets of keys cause 
                a ValueError on insertion. Defaults to None.
            mode (str, optional): "live" or "replay". Track usage mode. 
                Defaults to 'live'.
            save_mode (str, optional): "continuous", "on-demand", or "none". Determines 
                how data is dumped to disk, and how checkpoints are saved. 
                Defaults to 'continuous'.
            checkpoint_interval (int, optional): Seconds between automated saves. 
                Defaults to 120.
            max_checkpoint_files (int, optional): Maximum number of checkpoint files 
                to keep in the directory. Defaults to 3.
            trim_fraction (float, optional): The fraction of data points removed when 
                the set grows too large. Defaults to 0.5.
            max_datapoints (int or float, optional): Maximum number of data points 
                retained in memory. Defaults to 1e5.
            output_dir (str, optional): Directory for saving files (exports/checkpoints).
                Defaults to 'data' if not specified.
        """        
        # Initialize the fields with defaults
        self.data_points = data_points if data_points is not None else []
        """List of data points (`DataPoint` objects)"""
        self.field_names = field_names
        """Expected keys in each data point's `input_data`"""
        self.mode = mode
        """Replay or live mode toggle"""
        self.save_mode = save_mode
        """Determines how checkpoints are saved"""
        self.checkpoint_interval = checkpoint_interval
        """Time in seconds between two checkpoint files""" 
        self.max_checkpoint_files = max_checkpoint_files
        """Maximum number of checkpoint files to keep"""
        self.output_dir = output_dir if output_dir is not None else 'data'
        """Directory for saving files"""
        self.trim_fraction = trim_fraction
        """Fraction of points to trim before starting save run"""
        self.max_datapoints = max_datapoints
        """Maximum number of datapoints stored before full removal"""
        self.export_methods = _export_methods
        """Dictionary of available export methods"""
        self.preprocessors = []
        # Append-only file
        self.track_file = os.path.join(self.output_dir, "track.jsonl")
        self._file_handle = None

        """List of available preprocessing function for incoming data"""
        # Internal attributes not exposed as parameters
        self._replay_index = 0
        self._last_checkpoint = None
        self._save_interval_start = None
        
        # Setup directories for output and checkpoints
        self.checkpoint_dir = os.path.join(self.output_dir, 'chk')
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.checkpoint_dir, exist_ok=True)

        self.current_file = os.path.join(self.checkpoint_dir, "current.chk.json")

        # Setup logger
        self.logger = logging.getLogger("Track")
        self.logger.info("-------------Track-------------")
        self.logger.info(f'output directory: {self.output_dir}')
        self.logger.info(f'checkpoint directory: {self.checkpoint_dir}')
        
    def __str__(self):
        """
        Return a tabular view (string) of all data points.

        Uses the `tabulate` library to display a table with columns 
        for 'timestamp' and each field in `field_names`.

        Returns:
            str: A formatted table. If there are no data points, returns a string 
            stating that no data are available.
        """
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
        """
        Load a Track from a JSON file.

        The JSON is expected to be a list of serialized `DataPoint` objects. 
        After loading, the Track is placed in 'replay' mode.

        Args:
            filename (str): Path to the JSON file containing the Track data.

        Raises:
            RuntimeError: If the file cannot be parsed as JSON.
        """
        with open(filename, 'r') as f:
            try:
                data = json.load(f)
            except:
                self.logger.critical(f'could not load {filename} into a Track')
                raise RuntimeError(f'could not load {filename} into a Track')

        self.data_points = [DataPoint(datetime.fromisoformat(dp["timestamp"]), dp["input_data"]) for dp in data]
        self.mode = 'replay'
        
    def save(self, file_format='json', fname=None, output_dir=None, interval=None):
        """
        Save track data to a file in JSON, CSV, or GPX format. Users can
        also provide a callable for custom export.

        Args:
            file_format (str): Must be one of 'json', 'csv', or 'gpx'. You can
                also provide a callable for custom export.
            fname (str, optional): Output filename without extension. Defaults
                to a timestamp-based name if None.
            output_dir (str, optional): Directory in which to write the file.
                Defaults to `self.output_dir`.
            interval (slice, optional): Slice of `data_points` to export.

        Raises:
            RuntimeError: If an unrecognized file format is specified or if
                the underlying export method encounters an error.
        """
        # File name and directory
        if fname is None:
            fname = f'{datetime.now().strftime("%Y%m%d-%H%M%S")}'

        if output_dir is None:
            output_dir = self.output_dir
            
        # Strategy - check if file_format is key in export_methods
        if file_format in self.export_methods:
            export = self.export_methods[file_format]
        elif callable(file_format):
            # If file_format is callable, use it as the export function
            export = file_format
        else:
            self.logger.critical(f"unsupported file format: {file_format}")
        
        # Export
        try:
            file_path = os.path.join(output_dir, fname + '.' + file_format)
            export(self.data_points, file_path, interval=interval)
            self.logger.info(f"saving track to {file_format}: {file_path}")
        except Exception as e:
            import traceback
            self.logger.critical(f'error in saving track: {e}')
            print(traceback.format_exc())
    
    def _remove_datapoints(self, start=0, fraction=0.1):
        """
        Remove a subset of data points from memory.

        This is typically called when the number of data points grows
        beyond `max_datapoints`, or if you need to trim older data.

        Args:
            start (int, optional): Index in `data_points` at which removal begins. 
                Defaults to 0.
            fraction (float, optional): Fraction of total data points to remove (0.1 = 10%).
                Values over 1.0 are clamped to 1.0. Defaults to 0.1.
        """
        if not self.data_points:
            self.logger.warn("no data points to clear")
            return

        fraction = max(0.0, min(fraction, 1.0))
        num_to_remove = int(len(self.data_points) * fraction)

        start = max(0, min(start, len(self.data_points) - 1))
        end = min(start + num_to_remove, len(self.data_points))

        # Remove the specified range
        del self.data_points[start:end]
        self.logger.info(f"cleared {num_to_remove} data points from index {start} to {end-1}; remaining: {len(self.data_points)}")
                
    def start_run(self):
        """
        Transition the Track to continuous saving mode.

        If the current `save_mode` is 'on-demand', changes it to 'continuous'
        and trims older data as needed. This indicates that new data points
        will be saved periodically via checkpoints.
        """
        if self.save_mode == 'on-demand':
            self.save_mode = 'continuous'
            # Save index of first frame to be saved
            self._save_interval_start = len(self.data_points) - 1
            # Trim "useless" data points before first frame
            if self._save_interval_start > 0:
                self._remove_datapoints(fraction=self.trim_fraction)
            self.logger.info('logging data')
        elif self.save_mode == 'continuous':
            self.logger.warning(f'cannot start track saving on demand; current saving mode is {self.save_mode}')

    def end_run(self):
        """
        Forza un ultimo checkpoint e chiude la sessione.
        Mantiene il file in current.chk.json senza creare duplicati.
        """
        if self.save_mode == 'none':
            self.logger.warning("save_mode è 'none'; niente da chiudere")
            return

        # ultimo checkpoint in current.chk.json
        self._save_checkpoint(force=True)
        self.logger.info(f"ultimi dati salvati in {self.current_file}")

        # Reset stato
        self._save_interval_start = None
        self._last_checkpoint = None
        self.save_mode = 'on-demand'

    def _save_checkpoint(self, force: bool = False, specifier: str | None = None):
        """
        Salva periodicamente TUTTI i datapoint correnti in un unico file JSON.
        Il file viene sovrascritto ogni volta (rolling file).
        """
        if self.save_mode != 'continuous' or self.checkpoint_interval is None:
            return

        now = datetime.now()
        if not force and self._last_checkpoint is not None:
            dt = (now - self._last_checkpoint).total_seconds()
            if dt < self.checkpoint_interval:
                return

        self._last_checkpoint = now

        # intervallo da salvare (se stai usando on‑demand)
        if self._save_interval_start is not None:
            interval = slice(self._save_interval_start, len(self.data_points))
        else:
            interval = slice(0, len(self.data_points))

        try:
            # usa già la tua logica di export
            export = self.export_methods.get("json")
            if export is None:
                raise RuntimeError("json export method not available")

            export(self.data_points[interval], self.current_file)
            self.logger.info(f"checkpoint salvato in {self.current_file}")
        except Exception as e:
            self.logger.critical(f"errore nel salvataggio checkpoint: {e}")

    def add_point(self, timestamp: datetime, data: Dict[str, Any]):
        """
        Add a new data point to the Track, respecting field consistency.
        
        If the number of datapoints exceeds the threshold
        `self.max_datapoints`, all points are deleted from memory
        after saving a special checkpoint (with a `-full` specifier in
        the file name), a full track and raising a warning. This
        allows the user to replay the two saved tracks one after the
        other, without overlaps.

        Args:
            timestamp (datetime): The time the measurement was taken.
            data (dict[str, Any]): Key-value pairs of measurements for this data point.

        Raises:
            ValueError: If `field_names` is set and `data` keys differ from the expected keys.
        """
        # Validate or establish field consistency
        # NOTE: if no field names are passed, no checks are performed
        if self.field_names is not None and set(self.field_names) != set(data.keys()):
            raise ValueError(f"inconsistent fields. Expected {self.field_names}, got {list(data.keys())}")

        # Handle track longer than maximum number of datapoints
        if len(self.data_points) > self.max_datapoints:
            self.logger.warning("maximum number of datapoints reached; saving a checkpoint and wiping cache")
            self._save_checkpoint(force=True, specifier='-full')
            # Fraction of points to trim
            fraction = (len(self.data_points)-1)/len(self.data_points)
            self._remove_datapoints(fraction=fraction)

        # Pre-process data before generating the datapoint
        datapoint = DataPoint(timestamp, data)
        for processor in self.preprocessors:
            datapoint = processor(datapoint)

        # 🔥 APPEND-ONLY MINIMO: crea/appendi il file ad ogni datapoint
        try:
            with open(self.track_file, "a", buffering=1) as f:
                line = json.dumps(datapoint.to_dict())
                f.write(line + "\n")
        except Exception as e:
            self.logger.error(f"errore in append sul track file {self.track_file}: {e}")
       
        # Append the datapoint
        self.data_points.append(datapoint)
        # checkpoint periodico
        self._save_checkpoint()

        # controllo RAM dopo il salvataggio
        if len(self.data_points) > self.max_datapoints:
            self.logger.warning(
                "maximum number of datapoints reached; trimming old data"
            )
            self._remove_datapoints(fraction=self.trim_fraction)

    def get_latest_data(self):
        """
        Retrieve the most recent data point for each unique field.

        Returns:
            list[DataPoint]: A list of the most up-to-date `DataPoint` 
            objects across all fields. The length of this list is equal to 
            the number of unique fields encountered so far.
        """
        if not self.data_points:
            return []

        latest_data = {}
        for dp in self.data_points:
            for field, value in dp.data.items():
                latest_data[field] = dp  # Overwrite to get the most recent

        return list(latest_data.values())

    def get_current(self):
        """
        Return the current state of the Track, depending on mode.

        - In "live" mode, just returns self.
        - In "replay" mode, returns a partial Track up to `_replay_index`, which 
          increments each time you call this method.

        This is essential to replay a loaded Track from file, and to
        visualize it using other facilities (`WebApp`, ...)

        Returns:
            Track: A Track representing the current view of the data.
        """
        if self.mode == "live":
            return self  # In live mode, return the latest track
        elif self.mode == "replay":
            return self._get_replay_track()

    def _get_replay_track(self):
        """
        Internal method for replay functionality.

        Returns:
            Track: A partial track containing data up to `_replay_index`.

        Raises:
            ValueError: If there are no data points to replay.
        """
        if not self.data_points:
            raise ValueError("No data available for replay")

        # Limit replay index
        self._replay_index = min(self._replay_index + 1, len(self.data_points))

        # Create a new track with data up to the current replay index
        mock_track = Track()
        mock_track.field_names = self.field_names
        mock_track.data_points = self.data_points[:self._replay_index]

        return mock_track
