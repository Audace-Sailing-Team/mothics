import io
import zipfile
import os
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, Response, current_app, redirect, url_for, flash, send_file
from ..database import Database


database_bp = Blueprint('database', __name__)


def send_files_as_download(file_paths: list, zip_name_prefix: str = "download") -> Response:
    """
    Send one or more files as a download. If multiple, zip them in-memory.
    
    :param file_paths: List of Path objects (absolute paths)
    :param zip_name_prefix: Prefix for zip file name (used if multiple files)
    :return: Flask response with send_file
    """
    if not file_paths:
        flash("No valid files found for download.", "danger")
        return redirect(url_for('database.tracks_view'))

    if len(file_paths) == 1:
        fpath = os.path.join(current_app.config['INSTANCE_DIRECTORY'], file_paths[0])
        return send_file(fpath, as_attachment=True)

    # Zip multiple files into a buffer
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path in file_paths:
            path = os.path.join(current_app.config['INSTANCE_DIRECTORY'], path)
            zip_file.write(path, os.path.basename(path))
    zip_buffer.seek(0)

    zip_name = f"{zip_name_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(zip_buffer, mimetype="application/zip",
                     as_attachment=True, download_name=zip_name)


def refresh_all_tracks(db):
    try:
        db.load_tracks_incrementally()
        flash("All tracks refreshed successfully.", "success")
    except Exception as e:
        flash(f"Error refreshing tracks: {str(e)}", "danger")
    return redirect(url_for('database.tracks_view'))


def delete_tracks(db, track_ids):
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


def export_and_download_tracks(db, track_ids, export_format):
    if not export_format or export_format not in db.export_methods:
        flash("Invalid export format selected.", "warning")
        return redirect(url_for('database.tracks_view'))

    exported_files = []
    errors = []

    for track_id in track_ids:
        try:
            db.export_track(track_id, export_format=export_format)
            base_name, _ = os.path.splitext(track_id)
            exported_fname = f"{base_name}.{export_format}"
            exported_path = db.directory / exported_fname
            if exported_path.exists():
                exported_files.append(exported_path)
            else:
                errors.append(f"Exported file not found: {exported_fname}")
        except Exception as e:
            errors.append(f"Export error for track '{track_id}': {str(e)}")

    if errors:
        for err in errors:
            flash(err, "danger")
        return redirect(url_for('database.tracks_view'))

    return send_files_as_download(exported_files, zip_name_prefix="export")


@database_bp.route("/track/action", methods=["POST"])
def track_action():
    db = current_app.config['TRACK_MANAGER']
    track_ids = request.form.getlist("track_id")
    action = request.form.get("action")
    export_format = request.form.get("export_format")

    if action == "refresh_all":
        return refresh_all_tracks(db)

    if not track_ids:
        flash("No track selected.", "warning")
        return redirect(url_for('database.tracks_view'))

    match action:
        case "delete":
            return delete_tracks(db, track_ids)
        case "export":
            return export_and_download_tracks(db, track_ids, export_format)
        case _:
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

def track_download(track_ids):
    """
    Download selected original JSON track files.
    """
    db = current_app.config['TRACK_MANAGER']
    base_dir = current_app.config['INSTANCE_DIRECTORY']

    file_paths = []
    for track_id in track_ids:
        track = next((t for t in db.tracks if t["filename"] == track_id), None)
        if not track:
            continue
        if track.get("checkpoint"):
            path = base_dir / db.checkpoint_directory / track["filename"]
        else:
            path = base_dir / db.directory / track["filename"]
        if path.exists():
            file_paths.append(path)

    return send_files_as_download(file_paths, zip_name_prefix="tracks")


# def track_download(track_ids):
#     """
#     Download selected tracks. If one track is selected, download it directly.
#     If multiple tracks are selected, package them into a ZIP.
#     """
#     db = current_app.config['TRACK_MANAGER']

#     # Get file paths of the selected tracks
#     file_paths = []
#     for track_id in track_ids:
#         track = next((t for t in db.tracks if t["filename"] == track_id), None)
#         track_path = os.path.join(db.directory, track['filename'])
#         if track['checkpoint']:
#             track_path = os.path.join(db.checkpoint_directory, track['filename'])
#         file_paths.append(os.path.join(current_app.config['INSTANCE_DIRECTORY'], track_path))
            
#     if not file_paths:
#         flash("No valid tracks found.", "error")
#         return redirect(url_for('database.tracks_view'))

#     # Direct download for single file
#     if len(file_paths) == 1:
#         return send_file(file_paths[0], as_attachment=True)

#     # Zip multiple files
#     zip_buffer = io.BytesIO()
#     with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
#         for file_path in file_paths:
#             zip_file.write(file_path, os.path.basename(file_path))

#     zip_buffer.seek(0)
#     zip_fname = f'{datetime.now().strftime("%Y%m%d-%H%M%S")}.zip'
#     return send_file(zip_buffer, mimetype="application/zip", as_attachment=True, download_name=zip_fname)

