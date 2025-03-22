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

from .helpers import format_duration

# Validation schema
TRACK_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "timestamp": {"type": "string"},
            "input_data": {
                "type": "object",
                "patternProperties": {
                    ".*": {"type": ["number", "boolean", "string", "null"]}
                },
                "additionalProperties": False
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
        # Initialize TinyDB with caching middleware for better performance.
        self.db = TinyDB(os.path.join(self.directory, db_fname),
                         storage=CachingMiddleware(JSONStorage))
        self.validation = validation
        self.tracks = []
        self.rm_thesaurus = rm_thesaurus

        # Metadata extractor
        self.extractor = MetadataExtractor()
        
        # Setup logger
        self.logger = logging.getLogger("Database")
        self.logger.info("-------------Database-------------")

        # Load tracks
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

    def load_tracks(self):
        """
        Scan the directory for JSON files, including files in the 'chk' subdirectory.
        Validate each JSON file before extracting metadata and storing it in TinyDB.
        Files ending with '.chk.json' are flagged with a "Checkpoint" flag.
        """
        self.db.truncate()
        self.tracks = []

        def process_file(file: Path, is_checkpoint: bool):
            """Helper to validate and process a JSON file."""
            if self.validate_json(file) or not self.validation:
                meta = self.extractor.extract_all(file)
                meta["checkpoint"] = is_checkpoint
                self.db.insert(meta)
                self.tracks.append(meta)
            else:
                self.logger.warning(f"skipping invalid file: {file.name}")

        # Process main directory JSON files
        for file in self.directory.glob("*.json"):
            is_checkpoint = file.name.endswith(".chk.json")
            process_file(file, is_checkpoint)

        # Process 'chk' subdirectory JSON files
        chk_dir = self.directory / "chk"
        if chk_dir.exists() and chk_dir.is_dir():
            for file in chk_dir.glob("*.chk.json"):
                process_file(file, is_checkpoint=True)        
            
    def list_tracks(self) -> List[Dict[str, Any]]:
        """
        Returns the list of available tracks metadata from the database, formatted using tabulate (github style).
        Remote unit keys are converted using the rm_thesaurus.
        """
        self.tracks = self.db.all()  # Reload tracks from DB.
        if not self.tracks:
            self.logger.warning("no tracks available.")
            return []

        # Prepare tabular data.
        table_data = []
        for i, track in enumerate(self.tracks):
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

        # Define headers.
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

    def get_track_path(self, identifier: Union[int, str]) -> Optional[Path]:
        """
        Return full path for the selected track, identified by index or filename.
        If the track is a checkpoint, check both the main directory and 'chk' subdirectory.
        """
        self.tracks = self.db.all()

        if isinstance(identifier, int):  # Lookup by index
            if 0 <= identifier < len(self.tracks):
                track = self.tracks[identifier]
            else:
                self.logger.warning("invalid track index")
                return None
        elif isinstance(identifier, str):  # Lookup by filename
            track = next((t for t in self.tracks if t["filename"] == identifier), None)
            if not track:
                self.logger.warning(f"track with filename '{identifier}' not found in DB")
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
