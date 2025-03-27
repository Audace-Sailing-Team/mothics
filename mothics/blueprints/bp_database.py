from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, Response, current_app, redirect, url_for, flash
from ..database import Database


database_bp = Blueprint('database', __name__)

@database_bp.route("/track/action", methods=["POST"])
def track_action():
    """
    Handle track-related actions including refreshing tracks, deleting tracks, and exporting tracks.
    
    Supports actions:
    - Refresh all tracks
    - Delete selected tracks
    - Export selected tracks to a specified format
    """
    db = current_app.config['TRACK_MANAGER']
    track_ids = request.form.getlist("track_id")  # Get multiple selected track IDs
    action = request.form.get("action")
    export_format = request.form.get("export_format")

    # Refresh All Tracks Action
    if action == "refresh_all":
        try:
            db.load_tracks()
            flash("All tracks refreshed successfully.", "success")
        except Exception as e:
            flash(f"Error refreshing tracks: {str(e)}", "danger")
        return redirect(url_for('database.tracks_view'))

    # Validate track selection
    if not track_ids:
        flash("No track selected.", "warning")
        return redirect(url_for('database.tracks_view'))

    # Delete Tracks Action
    if action == "delete":
        deleted_count = 0
        for track_id in track_ids:
            track = next((t for t in db.tracks if t["filename"] == track_id), None)
            if track:
                try:
                    db.remove_track(track_id, delete_from_disk=True)
                    deleted_count += 1
                except Exception as e:
                    flash(f"Error deleting track '{track_id}': {str(e)}", "danger")
        flash(f"Deleted {deleted_count} track(s).", "success")
        return redirect(url_for('database.tracks_view'))

    # Export Tracks Action
    elif action == "export":
        # Validate export format
        if not export_format or export_format not in db.export_methods:
            flash("Invalid export format selected.", "warning")
            return redirect(url_for('database.tracks_view'))

        exported_count = 0
        for track_id in track_ids:
            track = next((t for t in db.tracks if t["filename"] == track_id), None)
            if track:
                try:
                    db.export_track(track_id, export_format=export_format)
                    exported_count += 1
                except Exception as e:
                    flash(f"Export error for track '{track_id}': {str(e)}", "danger")
        flash(f"Exported {exported_count} track(s) to {export_format}.", "success")
        return redirect(url_for('database.tracks_view'))

    # Fallback for unexpected actions
    flash("Invalid action requested.", "warning")
    return redirect(url_for('database.tracks_view'))


@database_bp.route("/tracks")
def tracks_view():
    if current_app.config['TRACK_MANAGER'] is None:
        db_dir = current_app.config['TRACK_MANAGER_DIRECTORY']
        db = Database(directory=db_dir, rm_thesaurus=current_app.config['RM_THESAURUS'])
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
        current_order=order,
        export_methods=db.export_methods
    )
