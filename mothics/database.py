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
    def __init__(self):
        # Setup logger
        self.logger = logging.getLogger("MetadataExtractor")
        self.logger.info("-------------MetadataExtractor-------------")

    def extract_track_datetime(self, filepath: Path, data: Any) -> Dict[str, Any]:
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
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            count = len(data.get("data", []))
        else:
            count = 0
        return {"datapoint_count": count}

    def extract_remote_units(self, filepath: Path, data: Any) -> Dict[str, Any]:
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
    def __init__(self, directory, db_fname="tracks_metadata.json", rm_thesaurus=None, validation=True):
        self.directory = Path(directory)
        """Database path."""
        self.checkpoint_directory = self.directory / "chk"
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
        Validate a JSON file against the schema.
        Returns True if valid, False otherwise.
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
        Incrementally load tracks: only re-validate & insert new/modified files,
        and remove DB entries whose files were deleted.
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
        Full rescan of the directory for JSON files, including 'chk' subdirectory.
        Validates and extracts metadata, and tracks available exports (e.g., gpx, csv).
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
        
    # def load_tracks(self):
    #     """
    #     Scan the directory for JSON files, including files in the 'chk' subdirectory.
    #     Validate each JSON file before extracting metadata and storing it in TinyDB.
    #     Files ending with '.chk.json' are flagged with a "Checkpoint" flag.
    #     """
    #     self.db.truncate()
    #     self.tracks = []

    #     def process_file(fname: Path, is_checkpoint: bool):
    #         """Helper to validate and process a JSON file."""
    #         if self.validate_json(fname) or not self.validation:
    #             meta = self.extractor.extract_all(fname)
    #             meta["checkpoint"] = is_checkpoint
    #             meta["filepath"] = fname
    #             self.db.insert(meta)
    #             self.tracks.append(meta)
    #         else:
    #             self.logger.warning(f"skipping invalid file: {file.name}")

    #     # Process main directory JSON files
    #     for fname in self.directory.glob("*.json"):
    #         # Skip database file
    #         if str(fname).split('/')[1] == self.db_fname:
    #             continue
    #         is_checkpoint = fname.name.endswith(".chk.json")
    #         process_file(fname, is_checkpoint)

    #     # Process 'chk' subdirectory JSON files
    #     if self.checkpoint_directory.exists() and self.checkpoint_directory.is_dir():
    #         for fname in self.checkpoint_directory.glob("*.chk.json"):
    #             process_file(fname, is_checkpoint=True)
            
    def list_tracks(self) -> List[Dict[str, Any]]:
        """
        Returns the list of available tracks metadata from the database, formatted using tabulate (github style).
        Remote unit keys are converted using the rm_thesaurus.
        """
        self.tracks = self.db.all()  # Reload tracks from DB.
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
        Return metadata for the selected track (by index) from the DB.
        """
        self.tracks = self.db.all()
        if 0 <= index < len(self.tracks):
            return self.tracks[index]
        self.logger.warning("invalid track index")
        return {}

    def get_track_path(self, track_id: Union[int, str]) -> Optional[Path]:
        """
        Return full path for the selected track, identified by index or filename.
        If the track is a checkpoint, check both the main directory and 'chk' subdirectory.
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
        Update the metadata for a given track identified by filename.
        """
        Track = Query()
        self.db.update(new_metadata, Track.filename == filename)
        # Reflect the update in our local list as well.
        self.tracks = self.db.all()

    def export_track(self, track_id: Union[int, str], export_format: str):
        """
        Export a track to the given format, unless the export already exists.
        Updates the track metadata with the list of available exports.
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

        
    # def export_track(self, track_id: Union[int, str], export_format: str):
    #     """
    #     Export the specified track to a different format by:
    #      1) Finding the original track JSON on disk
    #      2) Creating a temporary Track object
    #      3) Exporting it via the Track's export method

    #     :param track_id: The track filename (as stored in the DB) to export
    #     :param export_format: The format to export to (e.g. 'csv', 'json', etc.)
    #     """
    #     # Fetch JSON
    #     track_path = self.get_track_path(track_id)
    #     if not track_path:
    #         msg = f"track {track_id} not found in the file system."
    #         self.logger.warning(msg)
    #         return msg

    #     # Create temporary Track
    #     temp_track = Track(output_dir=self.directory)

    #     # Load JSON data temp Track
    #     try:
    #         temp_track.load(track_path.as_posix())
    #     except Exception as e:
    #         msg = f"Error loading track {track_id}: {e}"
    #         self.logger.warning(msg)
    #         return msg

    #     # Export data
    #     export_fname, _ = os.path.splitext(os.path.basename(track_path))
    #     try:
    #         temp_track.save(file_format=export_format, fname=export_fname)
    #     except Exception as e:
    #         msg = f"Error exporting track {track_id} to {export_format}: {e}"
    #         self.logger.critical(msg)
    #         return msg

    #     # Close temp Track
    #     del temp_track

    def remove_track(self, track_id: Union[int, str], delete_from_disk: bool=False):
        """
        Remove a track from the database, with an optional flag to delete the file from disk.

        :param identifier: Track identifier (index or filename)
        :param delete_from_disk: If True, physically delete the track file
        :return: Boolean indicating whether the track was successfully removed
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
