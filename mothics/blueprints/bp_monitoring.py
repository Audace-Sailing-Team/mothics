import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request, Response, current_app, abort, send_file
from ..helpers import compute_status, get_tile_zoom_levels

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route("/")
def index():
    auto_refresh = current_app.config['AUTO_REFRESH_TABLE']
    return render_template("index.html", auto_refresh=auto_refresh)


@monitor_bp.route("/api/get_table")
def get_table():
    database = current_app.config['GETTERS']['database']()
    data_points = database.data_points

    if not data_points:
        return render_template("table.html", table_data=[])

    latest_row = data_points[-1].to_dict()
    hidden = set(current_app.config.get('HIDDEN_DATA_CARDS') or [])
    data_thesaurus = current_app.config.get('DATA_THESAURUS', {})

    # Extract all sample rates into a dictionary keyed by their base path.                
    # This makes it easy to associate a sample rate with its corresponding metric.    
    sample_rates = {}
    for key, value in latest_row.items():
        if key.endswith('/sample_rate'):
            base = key.rsplit('/', 1)[0]
            sample_rates[base] = value

    # Build the filtered row with each metric as a nested dictionary.
    # This structure allows for future expansion (e.g. adding units, quality indicators, etc.) 
    filtered_row = {}
    for key, value in latest_row.items():
        # Skip hidden keys, last_timestamp entries, and sample_rate keys (already handled)
        if '/last_timestamp' in key or key in hidden or key.endswith('/sample_rate'):
            continue
        # Use thesaurus for aliasing if defined, otherwise use the original key.
        alias = data_thesaurus.get(key, key)
        filtered_row[alias] = {'value': value}

        # Associate the sample rate if available
        base = key.rsplit('/', 1)[0]
        if base in sample_rates:
            filtered_row[alias]['sample_rate'] = sample_rates[base]

    # Include a global timestamp (for "Last Sampled") if available
    if 'timestamp' in latest_row:
        filtered_row['timestamp'] = latest_row['timestamp']

    # The template expects table_data as a list of rows
    return render_template("table.html", table_data=[filtered_row])


@monitor_bp.route("/api/get_status")
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


@monitor_bp.route("/api/gps_info")
def gps_info():
    db = current_app.config['GETTERS']['database']()
    latest = db.data_points[-1].to_dict() if db.data_points else {}

    lat_key = next((k for k in latest if k.endswith("/gps/lat")), None)
    lon_key = next((k for k in latest if k.endswith("/gps/long")), None)
    spd_key = next((k for k in latest if "/gps/speed" in k), None)

    lat = latest.get(lat_key)
    lon = latest.get(lon_key)
    speed = latest.get(spd_key) if spd_key else None

    status_key = next((k for k in latest if k.endswith("/gps/status")), None)
    gps_available = latest.get(status_key, False)

    tile_dir = current_app.config['GPS_TILES_DIRECTORY']
    track_variable = current_app.config.get('TRACK_VARIABLE', 'speed')
    track_thresholds = current_app.config.get('TRACK_THRESHOLDS', [1, 5, 15])
    track_colors = current_app.config.get('TRACK_COLORS', ["#3366cc", "#66cc66", "#ffcc00", "#cc3333"])
    track_units = current_app.config.get('TRACK_UNITS', None)
    min_zoom, max_zoom = get_tile_zoom_levels(tile_dir=tile_dir)

    return jsonify({
        "gps_available": gps_available,
        "latest_position": {
            "lat": lat,
            "lon": lon,
            "speed": speed
        } if gps_available else None,
        "zoom": {
            "min": min_zoom,
            "max": max_zoom
        },
        "track_coloring": {
            "key": track_variable,
            "thresholds": track_thresholds,
            "colors": track_colors,
            "units": track_units
        }
    })


@monitor_bp.route("/api/gps_track")
def gps_track():
    db = current_app.config['GETTERS']['database']()
    window_minutes = current_app.config.get("GPS_HISTORY_MINUTES", 10)
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)

    # Filter all data points newer than the cutoff timestamp
    datapoints = [
        dp for dp in db.data_points
        if "timestamp" in dp.to_dict() and
        datetime.fromisoformat(dp.to_dict()["timestamp"]) >= cutoff
    ]
    
    track_data = []

    track_key = current_app.config.get("TRACK_VARIABLE", "speed")
    for dp in datapoints:
        d = dp.to_dict()

        lat_key = next((k for k in d if k.endswith("/gps/lat")), None)
        lon_key = next((k for k in d if k.endswith("/gps/long")), None)
        value_key = next((k for k in d if track_key in k and "/gps/" in k), None)

        if lat_key and lon_key:
            lat = d[lat_key]
            lon = d[lon_key]
            val = d.get(value_key)

            track_data.append({
                "lat": lat,
                "lon": lon,
                "value": val,
                "timestamp": d.get("timestamp")
            })

    return jsonify({"track": track_data})

@monitor_bp.route("/api/track_plot_data")
def track_plot_data():
    track = current_app.config['GETTERS']['database']()
    if not track:
        return jsonify({"error": "No track loaded"}), 400

    # ——— gather points & all distinct variable names ———
    points      = list(track.data_points)
    all_keys    = {k for p in points for k in p.input_data.keys()}
    hidden      = set(current_app.config.get("HIDDEN_DATA_PLOTS", []))
    thesaurus   = current_app.config.get("DATA_THESAURUS", {})
    filter_set  = set(request.args.get("vars", "").split(",")) if request.args.get("vars") else None

    # ——— build zero-filled (or None-filled) matrix up front ———
    vars_by_name = {
        k: [None] * len(points)      # placeholder for every timestamp
        for k in all_keys
        if (filter_set is None or k in filter_set) and k not in hidden
    }

    # ——— fill in the slots we actually have ———
    for idx, dp in enumerate(points):
        for k, raw in dp.input_data.items():
            if k in vars_by_name:
                try:
                    vars_by_name[k][idx] = float(raw)
                except (ValueError, TypeError):
                    pass  # leave None in place

    return jsonify(
        timestamps=[p.timestamp.isoformat() for p in points],
        vars=vars_by_name,
        aliases={k: thesaurus.get(k, k) for k in vars_by_name}
    )
