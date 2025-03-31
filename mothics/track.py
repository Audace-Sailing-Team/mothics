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

    
# Track export methods
def _export_base(data_points, filename, interval=None, field_names=None):
    """Base class for Track exporting"""
    pass

def export_to_json(data_points, filename, interval=None, field_names=None):
    """Exports the database to a JSON file."""
    if data_points is None:
        raise RuntimeError("no data points to save.")
    
    # Slice data_point list
    data_points_to_export = data_points
    if interval is not None:
        data_points_to_export = data_points[interval]

    with open(filename, mode='w') as jsonfile:
        json.dump([asdict(dp) for dp in data_points_to_export], jsonfile, default=str, indent=4)

def export_to_csv(data_points, filename, interval=None, field_names=None):
    """Exports the database to a CSV file."""
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
    """Exports the track to a GPX file."""
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
        time = ET.SubElement(trkpt, "time")
        time.text = dp.timestamp.isoformat()  # Timestamp in ISO 8601 format

    # Write the GPX file
    tree = ET.ElementTree(gpx)
    tree.write(filename)

_export_methods = {'json': export_to_json, 'csv': export_to_csv, 'gpx': export_to_gpx}


# Track
class Track:
    def __init__(self,
                 data_points: Optional[List[DataPoint]] = None,
                 field_names: Optional[List[str]] = None,
                 mode: Optional[str] = 'live',
                 save_mode: Optional[str] = 'continuous',
                 checkpoint_interval: Optional[int] = 30,
                 max_checkpoint_files: Optional[int] = 3,
                 trim_fraction: Optional[float] = 0.5,
                 max_datapoints: Optional[int] = 1e5,
                 output_dir: Optional[str] = None):
        # Initialize the fields with defaults
        self.data_points = data_points if data_points is not None else []
        self.field_names = field_names
        self.mode = mode
        """Replay or live mode toggle"""
        self.save_mode = save_mode
        self.checkpoint_interval = checkpoint_interval
        """Time in seconds between two checkpoint files""" 
        self.max_checkpoint_files = max_checkpoint_files
        """Maximum number of checkpoint files to keep"""
        self.output_dir = output_dir if output_dir is not None else 'data'
        self.trim_fraction = trim_fraction
        """Fraction of points to trim before starting save run"""
        self.max_datapoints = max_datapoints
        """Maximum number of datapoints stored before full removal"""
        self.export_methods = _export_methods
        """Dictionary of available export methods"""
        self.preprocessors = []
        """List of available preprocessing function for incoming data"""
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
        
    def save(self, file_format='json', fname=None, output_dir=None, interval=None):
        """
        Save track on JSON or CSV file.
        Note: `file_format` must coincide with the file extension
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
        """Remove data points from memory according to a specified percentage from a given starting point (i.e., point index).

        Args:
            start (int): The index from where deletion should begin.
            fraction (float): The fraction of total data points to remove (0.1 = 10%).
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
        """Start a sampling run"""
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
        """End a sampling run"""
        if self.save_mode != 'on-demand': # FLAWED current save status check
            # Generate slice and save track
            interval = slice(self._save_interval_start, len(self.data_points) - 1)
            self.save(interval=interval)
            # Cleanup checkpoint storage (except -full files)
            chk_files_all= glob.glob(os.path.join(self.checkpoint_dir, "*.chk.json"))
            chk_files = [f for f in chk_files_all if not re.search(r"-full\.chk\.json$", f)]
            for f in chk_files:
                os.remove(f)
            # Clean up interval indices and reset mode
            self._save_interval_start = None
            self._last_checkpoint = None
            self.save_mode = 'on-demand'
            self.logger.info('data logging ended')
        else:
            self.logger.warning(f'cannot end track saving; current saving mode is {self.save_mode}')
    
    def _save_checkpoint(self, force=False, specifier=None):
        """Save a checkpoint after a certain amount of seconds"""
        if self.save_mode == 'continuous' and self.checkpoint_interval is not None:
            now = datetime.now()
            # Save a checkpoint if above time threshold (or no points are available)
            if self._last_checkpoint is None or (now - self._last_checkpoint).total_seconds() > self.checkpoint_interval or force:
                self._last_checkpoint = now
                interval = slice(self._save_interval_start, len(self.data_points) - 1)
                fname=f'{now.strftime("%Y%m%d-%H%M%S")}.chk'
                if specifier is not None:
                    fname=f'{now.strftime("%Y%m%d-%H%M%S")+str(specifier)}.chk'
                self.save(interval=interval, fname=fname, output_dir=self.checkpoint_dir)

            # Remove older files from checkpoint directory
            chk_files_all= glob.glob(os.path.join(self.checkpoint_dir, "*.chk.json"))
            # Remove all checkpoints with the `-full` specifier
            chk_files = [f for f in chk_files_all if not re.search(r"-full\.chk\.json$", f)]
            chk_files.sort(key=os.path.getmtime)
            
            if len(chk_files) > self.max_checkpoint_files:
                # Delete the oldest file
                os.remove(chk_files[0])

    def add_point(self, timestamp: datetime, data: Dict[str, Any]):
        """Add a data point ensuring field consistency."""
        # Validate or establish field consistency
        # NOTE: if no field names are passed, no checks are performed
        if self.field_names is not None and set(self.field_names) != set(data.keys()):
            raise ValueError(f"inconsistent fields. Expected {self.field_names}, got {list(data.keys())}")

        # NOTE: if the number of datapoints exceeds the threshold
        # `max_datapoints`, all points are deleted from memory after
        # saving a special checkpoint, a full track and raising a
        # warning. This allows the user to replay the two saved tracks
        # one after the other, without overlaps.
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
       
        # Append the datapoint
        self.data_points.append(datapoint)
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
