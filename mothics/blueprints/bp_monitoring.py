import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request, Response, current_app, abort, send_file
from bokeh.embed import server_document
from ..bokeh_plots import PlotDispatcher
from ..helpers import compute_status

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route("/")
def index():
    dispatcher = PlotDispatcher(current_app.config)
    script, div = dispatcher.render()
    auto_refresh = current_app.config['AUTO_REFRESH_TABLE']
    return render_template("index.html", script=script, div=div, auto_refresh=auto_refresh)

@monitor_bp.route("/get_table")
def get_table():
    database = current_app.config['GETTERS']['database']()
    data_points = database.data_points

    if not data_points:
        return render_template("table.html", table_data=[])

    latest_row = data_points[-1].to_dict()
    hidden = set(current_app.config.get('HIDDEN_DATA_CARDS') or [])
    data_thesaurus = current_app.config.get('DATA_THESAURUS', {})

    # Filter + apply thesaurus in one loop
    filtered_row = {
        data_thesaurus.get(key, key): value
        for key, value in latest_row.items()
        if '/last_timestamp' not in key and key not in hidden
    }

    return render_template("table.html", table_data=[filtered_row])

@monitor_bp.route("/get_status")
def get_status():
    database = current_app.config['GETTERS']['database']()
    latest_data = database.data_points[-1].to_dict() if database.data_points else {}
    now = latest_data['timestamp']
    
    # Compute status for each remote unit
    status_data = {rm.split('/')[0]: compute_status(ts, now=now, timeout_noncomm=current_app.config.get('TIMEOUT_NONCOMM', 30), timeout_offline=current_app.config.get('TIMEOUT_OFFLINE', 60)) for rm, ts in latest_data.items() if 'last_timestamp' in rm}

    # Apply remote unit thesaurus if available
    rm_thesaurus = current_app.config['RM_THESAURUS']
    if rm_thesaurus:
        status_data = {rm_thesaurus.get(rm, rm): status for rm, status in status_data.items()}
    return render_template("status.html", status_data=status_data)

@monitor_bp.route('/tiles/<int:z>/<int:x>/<int:y>.png')
def serve_tile(z, x, y):
    path = os.path.join(current_app.root_path, 'static', 'tiles', str(z), str(x), f"{y}.png")
    if os.path.exists(path):
        return send_file(path)
    else:
        abort(404)

@monitor_bp.route("/gps_map")
def gps_map():
    return render_template("gps_map.html")

@monitor_bp.route("/api/latest_gps")
def api_latest_gps():
    db = current_app.config['GETTERS']['database']()
    if not db.data_points:
        return jsonify({'error': 'no data'}), 204  # no content

    latest = db.data_points[-1].to_dict()

    lat_key = next((k for k in latest if k.endswith("/gps/lat")), None)
    lon_key = next((k for k in latest if k.endswith("/gps/long")), None)
    spd_key = next((k for k in latest if "/gps/speed" in k), None)

    lat = latest.get(lat_key)
    lon = latest.get(lon_key)
    speed = latest.get(spd_key) if spd_key else None

    if lat is None or lon is None:
        return jsonify({'error': 'no gps'}), 204

    return jsonify({
        'lat': lat,
        'lon': lon,
        'speed': speed
    })
