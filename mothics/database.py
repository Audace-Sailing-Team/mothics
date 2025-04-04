"""
This module integrates a local TinyDB instance to store and manage track metadata,
including checkpoints and exports, as well as a `MetadataExtractor` utility for
collecting high-level information about each track file. It also validates JSON
track files against a predefined schema and monitors changes in the filesystem,
keeping the database in sync.

Classes
-------
- MetadataExtractor: Extracts metadata (timestamp, duration, remote units, etc.) 
  from JSON track files.
- Database: Maintains a TinyDB database of all discovered track files, 
  enabling incremental updates, file validation, listing, and exporting.

Notes
-----
- Use `load_tracks()` for a full directory rescan, or `load_tracks_incrementally()`
  to detect only new/modified files.
- `validate_json()` is used internally to ensure each track file adheres to the
  required schema (`TRACK_SCHEMA`).
- The `MetadataExtractor` methods can be extended if you need additional metadata
  (e.g., sensor statistics or geospatial bounding boxes).
"""

import re
import glob
import os
import csv
import json
import logging
from pathlib import Path
from tabulate import tabulate
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware
from jsonschema import validate, ValidationError
from collections import defaultdict

from .helpers import format_duration
from .track import _export_methods, Track


# Validation schema
# TODO: load schema from external file
TRACK_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "timestamp": {"type": "string"},
            "input_data": {
                "type": "object",
                # Allow all string keys and allow typical sensor data types
                "additionalProperties": {
                    "type": ["number", "string", "boolean", "null"]
                }
            }
        },
        "required": ["timestamp", "input_data"]
    }
}


class MetadataExtractor:
    """
    Extracts various pieces of metadata from a JSON track file.

    This helper class provides multiple extractor methods to gather:
    - approximate track datetime (parsed from filename)
    - track duration (start to end timestamp)
    - total data point count
    - remote units involved in the track
    - any additional common data keys

    Attributes:
        logger (logging.Logger): Logger instance for debug/info/error messages.
    """
    
    def __init__(self):
        """
        Initialize the MetadataExtractor, setting up the logger.
        """
        # Setup logger
        self.logger = logging.getLogger("MetadataExtractor")
        self.logger.info("-------------MetadataExtractor-------------")

    def extract_track_datetime(self, filepath: Path, data: Any) -> Dict[str, Any]:
        """
        Attempt to parse a track datetime from the file name.

        Args:
            filepath (Path): The path of the file being processed.
            data (Any): The JSON data that was loaded from `filepath`.

        Returns:
            dict: A dictionary with a 'track_datetime' key (ISO 8601 string or None).
        """
        pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}|\d{8}-\d{6})'
        match = re.search(pattern, filepath.name)
        if match:
            dt_str = match.group(1)
            try:
                if "-" in dt_str and ":" not in dt_str:
                    dt = datetime.strptime(dt_str, '%Y%m%d-%H%M%S')
                else:
                    dt_formatted = dt_str[:10] + " " + dt_str[11:].replace('-', ':')
                    dt = datetime.strptime(dt_formatted, '%Y-%m-%d %H:%M:%S')
                return {"track_datetime": dt.isoformat()}
            except ValueError as ve:
                self.logger.warning(f"Date parsing error in file {filepath.name}: {ve}")
        return {"track_datetime": None}

    def extract_datapoint_count(self, filepath: Path, data: Any) -> Dict[str, Any]:
        """
        Count the number of data points in a track file.

        Args:
            filepath (Path): The file's location on disk.
            data (Any): Parsed JSON data (list of dict or a dict with "data" list).

        Returns:
            dict: A dictionary with a 'datapoint_count' key indicating the total data points.
        """
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            count = len(data.get("data", []))
        else:
            count = 0
        return {"datapoint_count": count}

    def extract_remote_units(self, filepath: Path, data: Any) -> Dict[str, Any]:
        """
        Identify unique remote units from the earliest data record.

        Remote unit name is parsed as the substring before the first '/' or '_'
        (depending on data style).

        Args:
            filepath (Path): The track file path.
            data (Any): Parsed JSON structure for the track.

        Returns:
            dict: A dictionary with 'remote_units', a list of discovered unit names.
        """
        remote_units = set()
        if isinstance(data, list) and data:
            first_dp = data[0]
            if isinstance(first_dp, dict) and "input_data" in first_dp:
                for key in first_dp["input_data"].keys():
                    unit = key.split("/")[0]
                    remote_units.add(unit)
        elif isinstance(data, dict):
            datapoints = data.get("data", [])
            if datapoints and isinstance(datapoints[0], dict):
                for key in datapoints[0].keys():
                    unit = key.split("_")[0]
                    remote_units.add(unit)
        return {"remote_units": list(remote_units)}

    def extract_additional_metadata(self, filepath: Path, data: Any) -> Dict[str, Any]:
        """
        Extract a list of keys that appear in every data point.

        Useful for identifying common sensor fields.

        Args:
            filepath (Path): The file path.
            data (Any): The JSON data loaded from disk.

        Returns:
            dict: A dictionary with 'common_datapoint_keys' 
                  indicating the shared sensor fields across all data points.
        """
        metadata = {}
        if isinstance(data, list) and data:
            if "input_data" in data[0]:
                common_keys = set(data[0]["input_data"].keys())
                for dp in data[1:]:
                    if "input_data" in dp:
                        common_keys.intersection_update(dp["input_data"].keys())
                metadata["common_datapoint_keys"] = list(common_keys)
        elif isinstance(data, dict):
            datapoints = data.get("data", [])
            if datapoints and isinstance(datapoints[0], dict):
                common_keys = set(datapoints[0].keys())
                for dp in datapoints[1:]:
                    common_keys.intersection_update(dp.keys())
                metadata["common_datapoint_keys"] = list(common_keys)
        return metadata

    def extract_track_duration(self, filepath: Path, data: Any) -> Dict[str, Any]:
        """
        Compute the total duration of the track based on the earliest
        and latest timestamps in the file.

        Args:
            filepath (Path): The path to the track file.
            data (Any): The parsed JSON content.

        Returns:
            dict: Dictionary with 'track_duration' in seconds or None if unavailable.
        """
        def parse_timestamp(ts_str):
            try:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

        start_ts = end_ts = None
        try:
            if isinstance(data, list) and data:
                start_ts = parse_timestamp(data[0].get("timestamp"))
                end_ts = parse_timestamp(data[-1].get("timestamp"))
            elif isinstance(data, dict):
                datapoints = data.get("data", [])
                if datapoints:
                    start_ts = parse_timestamp(datapoints[0].get("timestamp"))
                    end_ts = parse_timestamp(datapoints[-1].get("timestamp"))
        except Exception as e:
            self.logger.warning(f"Error computing track duration for {filepath.name}: {e}")

        if start_ts and end_ts:
            return {"track_duration": (end_ts - start_ts).total_seconds()}
        return {"track_duration": None}

    def extract_all(self, filepath: Path) -> Dict[str, Any]:
        """
        Apply all available extractors to the specified file.

        Args:
            filepath (Path): The path to the JSON file containing track data.

        Returns:
            dict: A dictionary of extracted metadata (filename, track_datetime, etc.).
        """
        metadata = {"filename": filepath.name}
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except Exception as e:
            self.logger.warning(f"Error reading {filepath.name}: {e}")
            return metadata

        extractors = [
            self.extract_track_datetime,
            self.extract_track_duration,
            self.extract_datapoint_count,
            self.extract_remote_units,
            self.extract_additional_metadata,
        ]

        for extractor in extractors:
            try:
                metadata.update(extractor(filepath, data))
            except Exception as e:
                self.logger.warning(f"Error in extractor {extractor.__name__} for {filepath.name}: {e}")
        return metadata


class Database:
    """
    Maintains a TinyDB database of track metadata, providing utilities to
    - validate and load track files from disk
    - incrementally update the database if tracks are added/removed/modified
    - list available tracks in a tabular form
    - export track data into different formats
    - delete tracks from the database and optionally from disk.
    """
    
    def __init__(self, directory, db_fname="tracks_metadata.json", rm_thesaurus=None, validation=True):
        """
        Initialize the Database instance.

        Args:
            directory (str or Path): The filesystem path where track JSON files 
                and optionally a 'chk' subdirectory are located.
            db_fname (str, optional): The TinyDB file name. Defaults to "tracks_metadata.json".
            rm_thesaurus (dict, optional): A mapping for remote unit aliases, e.g.
                {"rm1": "Unit 1", "rm2": "Unit 2"}. Defaults to None.
            validation (bool, optional): If True, each track JSON must pass 
                schema validation before insertion. Defaults to True.
        """
        self.directory = Path(directory)
        """Database path"""
        self.checkpoint_directory = self.directory / "chk"
        """Checkpoint directory path."""
        self.db_fname = db_fname
        """Database file name."""
        self.validation = validation
        """Require track validation on insertion in database"""
        self.rm_thesaurus = rm_thesaurus
        """Aliases for remote unit names"""
        self.export_methods = _export_methods
        """Export functions for tracks"""
        
        # Initialize TinyDB with caching middleware for better performance.
        self.db = TinyDB(os.path.join(self.directory, db_fname),
                         storage=CachingMiddleware(JSONStorage))
        self.tracks = []

        # Metadata extractor
        self.extractor = MetadataExtractor()
        
        # Setup logger
        self.logger = logging.getLogger("Database")
        self.logger.info("-------------Database-------------")

        # Load tracks (scan directory and load)
        self.load_tracks()

    def validate_json(self, filepath: Path):
        """
        Validate a JSON file against the global TRACK_SCHEMA.

        Args:
            filepath (Path): The JSON file to check.

        Returns:
            bool: True if valid, False otherwise.
        """
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            validate(instance=data, schema=TRACK_SCHEMA)
            return True
        except (json.JSONDecodeError, ValidationError) as e:
            self.logger.warning(f"validation error in {filepath.name}: {e}")
            return False

    def load_tracks_incrementally(self):
        """
        Incrementally update the database. This only re-validates and
        inserts new/modified files, and removes DB entries whose files
        were deleted.
        """
        # Grab everything that's currently in TinyDB
        existing_tracks = {t["filename"]: t for t in self.db.all()}
        
        # Build a set of (filename -> last modification time) from the filesystem
        found_files = {}
        for fname in self.directory.glob("*.json"):
            if fname.name == self.db_fname:
                continue
            found_files[fname.name] = fname.stat().st_mtime

        # Include *.chk.json
        if self.checkpoint_directory.exists():
            for fname in self.checkpoint_directory.glob("*.chk.json"):
                found_files[fname.name] = fname.stat().st_mtime

        # Remove DB entries for files that no longer exist
        Track = Query()
        for db_filename in list(existing_tracks.keys()):
            if db_filename not in found_files:
                # remove from DB
                self.logger.info(f"Removing {db_filename} from DB (file missing on disk).")
                self.db.remove(Track.filename == db_filename)
                del existing_tracks[db_filename]

        # Exported files
        export_extensions = list(self.export_methods.keys())

        # Build list of known exported files
        existing_exports = defaultdict(list)
        for ext in export_extensions:
            for f in self.directory.glob(f"*.{ext}"):
                base = f.stem  # filename without extension
                existing_exports[base].append(ext)
        
        # Check if file is new or modified
        for fname, mtime in found_files.items():
            db_track = existing_tracks.get(fname)
            # If not in DB or modification time changed, re-validate + store
            if (not db_track) or (db_track.get("mtime") != mtime):
                # Validate and load metadata
                full_path = self.directory / fname
                # If it's a checkpoint file, we know to look in /chk
                is_checkpoint = fname.endswith(".chk.json")
                if is_checkpoint:
                    full_path = self.checkpoint_directory / fname

                if self.validate_json(full_path) or not self.validation:
                    meta = self.extractor.extract_all(full_path)
                    meta["checkpoint"] = is_checkpoint
                    meta["filename"] = fname
                    meta["filepath"] = full_path
                    meta["mtime"] = mtime  # Store the modification time

                    # Attach export info if any
                    base_name = fname.replace(".chk.json", "").replace(".json", "")
                    if base_name in existing_exports:
                        meta["exports"] = existing_exports[base_name]
                    
                    # If existed in DB, update; else insert
                    if db_track:
                        self.db.update(meta, Track.filename == fname)
                    else:
                        self.db.insert(meta)
                    self.logger.info(f"Updated DB entry for {fname} (new or changed).")

        # Update self.tracks in memory
        self.tracks = self.db.all()

    def load_tracks(self):
        """
        Perform a full rescan of the directory (and 'chk' subdirectory) for
        JSON track files, clearing the database before re-inserting everything.
        """
        self.db.truncate()
        self.tracks = []

        # Gather known exports before loading track metadata
        export_extensions = list(self.export_methods.keys())  # e.g., ['gpx', 'csv', ...]
        existing_exports = defaultdict(list)
        for ext in export_extensions:
            for f in self.directory.glob(f"*.{ext}"):
                base = f.stem  # filename without extension
                existing_exports[base].append(ext)

        def process_file(fname: Path, is_checkpoint: bool):
            """Helper to validate and process a JSON file."""
            if self.validate_json(fname) or not self.validation:
                meta = self.extractor.extract_all(fname)
                meta["checkpoint"] = is_checkpoint
                meta["filepath"] = fname
                meta["filename"] = fname.name

                # Attach available exports
                base_name = fname.stem.replace(".chk", "")
                if base_name in existing_exports:
                    meta["exports"] = sorted(existing_exports[base_name])

                self.db.insert(meta)
                self.tracks.append(meta)
            else:
                self.logger.warning(f"Skipping invalid file: {fname.name}")

        # Process JSON files in main directory
        for fname in self.directory.glob("*.json"):
            if fname.name == self.db_fname:
                continue
            is_checkpoint = fname.name.endswith(".chk.json")
            process_file(fname, is_checkpoint)

        # Process JSON files in 'chk' subdirectory
        if self.checkpoint_directory.exists() and self.checkpoint_directory.is_dir():
            for fname in self.checkpoint_directory.glob("*.chk.json"):
                process_file(fname, is_checkpoint=True)
                    
    def list_tracks(self) -> List[Dict[str, Any]]:
        """
        Print a table of discovered tracks and return their metadata,
        formatted using tabulate (github style)..
        Remote unit keys are converted using the rm_thesaurus.

        Returns:
            list[dict]: The entire list of track metadata from the database.
        """
        self.tracks = self.db.all()  # Reload tracks from DB
        if not self.tracks:
            self.logger.warning("no tracks available.")
            return []

        # Prepare tabular data
        table_data = []
        for i, track in enumerate(self.tracks):
            # Skip database file
            if track['filename'] == self.db_fname:
                continue
            # Get the list of remote unit keys.
            thesaurized_units = track.get("remote_units", [])
            if self.rm_thesaurus is not None:
                thesaurized_units = [self.rm_thesaurus[rm] for rm in thesaurized_units]
            table_data.append([
                i,
                track["filename"],
                track.get("track_datetime", "N/A"),
                track.get("checkpoint", "N/A"),
                format_duration(track.get("track_duration", "N/A")),
                track.get("datapoint_count", "N/A"),
                ", ".join(thesaurized_units)
            ])

        # Define headers
        headers = ["Index", "Filename", "Date/Time", "Checkpoint", "Duration", "Data Points", "Remote Units"]

        # Print table using github format.
        print(tabulate(table_data, headers=headers, tablefmt="github"))

        return self.tracks            

    def select_track(self, index: int) -> Dict[str, Any]:
        """
        Retrieve metadata for the track at a given list index.

        Args:
            index (int): Zero-based index of the track in the DB list.

        Returns:
            dict: The metadata dictionary for the requested track,
                  or empty if the index is invalid.
        """
        self.tracks = self.db.all()
        if 0 <= index < len(self.tracks):
            return self.tracks[index]
        self.logger.warning("invalid track index")
        return {}

    def get_track_path(self, track_id: Union[int, str]) -> Optional[Path]:
        """
        Determine the full filesystem path for a given track, by index or filename.

        If the track is marked as a checkpoint, checks the 'chk' subdirectory.
        Otherwise, looks in the main directory.

        Args:
            track_id (int|str): The index or filename identifying the track.

        Returns:
            Path or None: The path to the file, or None if not found.
        """
        self.tracks = self.db.all()

        if isinstance(track_id, int):  # Lookup by index
            if 0 <= track_id < len(self.tracks):
                track = self.tracks[track_id]
            else:
                self.logger.warning("invalid track index")
                return None
        elif isinstance(track_id, str):  # Lookup by filename
            track = next((t for t in self.tracks if t["filename"] == track_id), None)
            if not track:
                self.logger.warning(f"track with filename '{track_id}' not found in DB")
                return None
        else:
            self.logger.warning("invalid identifier type")
            return None

        filename = track["filename"]

        # Check if it's a checkpoint track
        if track.get("checkpoint", False):
            chk_path = self.directory / "chk" / filename
            if chk_path.exists():
                return chk_path

        # Default to searching in the main directory
        file_path = self.directory / filename
        if file_path.exists():
            return file_path

        self.logger.warning(f"File '{filename}' not found in expected directories.")
        return None
    
    def update_track_metadata(self, filename: str, new_metadata: Dict[str, Any]):
        """
        Update an existing track's metadata in the TinyDB.

        Args:
            filename (str): The track filename to update.
            new_metadata (dict): The fields to add/update in that track's metadata.
        """
        Track = Query()
        self.db.update(new_metadata, Track.filename == filename)
        # Reflect the update in our local list as well.
        self.tracks = self.db.all()

    def export_track(self, track_id: Union[int, str], export_format: str):
        """
        Export the specified track to the given format if it doesn't already exist; this
         1. retrieves the track's path and creates a temporary `Track` object
         2. loads the track JSON into `Track`
         3. exports via `Track.save(file_format=export_format)`
         4. updates the track's metadata in TinyDB to record that this export now exists.

        Args:
            track_id (int|str): The track index or filename to export.
            export_format (str): Format to export (e.g., 'json', 'csv', or 'gpx').
        """
        # Fetch track metadata
        self.tracks = self.db.all()
        track = None

        if isinstance(track_id, int):
            if 0 <= track_id < len(self.tracks):
                track = self.tracks[track_id]
        elif isinstance(track_id, str):
            track = next((t for t in self.tracks if t["filename"] == track_id), None)

        if not track:
            msg = f"track {track_id} not found in the database"
            self.logger.warning(msg)
            return msg

        base_name, _ = os.path.splitext(track["filename"])
        export_fname = f"{base_name}.{export_format}"
        export_path = self.directory / export_fname

        # If already exported, skip
        if export_path.exists():
            self.logger.info(f"{export_fname} already exists, skipping regeneration.")
        else:
            # Load track JSON into temporary Track object
            track_path = self.get_track_path(track_id)
            if not track_path:
                msg = f"track file not found for export: {track_id}"
                self.logger.warning(msg)
                return msg

            temp_track = Track(output_dir=self.directory)

            try:
                temp_track.load(track_path.as_posix())
                temp_track.save(file_format=export_format, fname=base_name)
            except Exception as e:
                msg = f"Error exporting track {track_id} to {export_format}: {e}"
                self.logger.critical(msg)
                return msg
            finally:
                del temp_track

            self.logger.info(f"Exported {track['filename']} to {export_format}")

        # Update exports in DB
        exports = set(track.get("exports", []))
        exports.add(export_format)
        self.update_track_metadata(track["filename"], {"exports": list(exports)})        

    def remove_track(self, track_id: Union[int, str], delete_from_disk: bool=False):
        """
        Remove a track from the TinyDB, optionally deleting the file from disk.

        Args:
            track_id (int|str): Index or filename identifying the track to remove.
            delete_from_disk (bool, optional): If True, physically delete the file 
                in addition to removing its DB entry.

        Raises:
            RuntimeError: If the track doesn't exist in DB or if there's an error 
                deleting from disk.
        """
        # Find the track path first
        track_path = self.get_track_path(track_id)
        if not track_path:
            self.logger.critical(f"cannot remove track: track {track_id} not found")
            raise RuntimeError(f"cannot remove track: track {track_id} not found")

        # Remove from database
        Track = Query()
        removal_count = self.db.remove(Track.filename == track_path.name)

        if removal_count == 0:
            self.logger.critical(f"no database entries found for track {track_id}")
            raise RuntimeError(f"no database entries found for track {track_id}")

        # Refresh tracks list
        self.tracks = self.db.all()

        # Optionally delete from disk
        if delete_from_disk:
            try:
                os.remove(track_path)
                self.logger.info(f"deleted track file: {track_path}")
            except [Exception, OSError] as e:
                self.logger.critical(f"error deleting track file {track_path}: {e}")
                raise RuntimeError(f"error deleting track file {track_path}: {e}")
            
        self.logger.info(f"successfully removed track: {track_path.name}")
