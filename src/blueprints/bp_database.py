from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, Response, current_app
from ..database import Database


database_bp = Blueprint('database', __name__)


@database_bp.route("/tracks")
def tracks_view():
    if current_app.config['TRACK_MANAGER'] is None:
        db_dir = current_app.config['TRACK_MANAGER_DIRECTORY']
        db = Database(directory=db_dir, rm_thesaurus={'rm1': 'GPS+IMU', 'rm2': 'Anemometer'})
        current_app.config['TRACK_MANAGER'] = db
    else:
        db = current_app.config['TRACK_MANAGER']
    
    # Get sort criteria from query parameters (with defaults)
    sort_by = request.args.get("sort_by", "filename")
    order = request.args.get("order", "asc")
    
    tracks = db.tracks

    # Define a key function for sorting
    def sort_key(track):
        if sort_by == "filename":
            return track.get("filename", "")
        elif sort_by == "track_datetime":
            try:
                return datetime.fromisoformat(track.get("track_datetime", ""))
            except Exception:
                return datetime.min
        elif sort_by == "checkpoint":
            # Boolean values are fine.
            return track.get("checkpoint", False)
        elif sort_by == "track_duration":
            # Return 0 if track_duration is None.
            duration = track.get("track_duration")
            return duration if duration is not None else 0
        elif sort_by == "datapoint_count":
            count = track.get("datapoint_count")
            return count if count is not None else 0
        elif sort_by == "remote_units":
            # Convert list of remote units to a string for sorting.
            return ", ".join(track.get("remote_units", []))
        return track.get(sort_by, "")
    
    reverse = order == "desc"
    tracks_sorted = sorted(tracks, key=sort_key, reverse=reverse)

    return render_template(
        "tracks.html",
        tracks=tracks_sorted,
        rm_thesaurus=db.rm_thesaurus,
        current_sort=sort_by,
        current_order=order
    )
