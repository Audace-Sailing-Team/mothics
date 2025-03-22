import os
from flask import Blueprint, render_template, jsonify, request, Response, current_app, abort, send_file
from bokeh.embed import server_document
from ..bokeh_apps.static import create_bokeh_plots
from ..helpers import compute_status

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route("/")
def index():
    # Select plot source
    mode = current_app.config['PLOT_MODE']
    if mode == 'real-time':
        # Use server_document to generate the script that will embed the Bokeh app.
        script = server_document(current_app.config['PLOT_REALTIME_URL'])
        div = ""
    else:
        database = current_app.config['GETTERS']['database']()
        script, div = create_bokeh_plots(database)
        
    auto_refresh = current_app.config['AUTO_REFRESH_TABLE']
    return render_template("index.html", script=script, div=div, auto_refresh=auto_refresh)

@monitor_bp.route("/get_table")
def get_table():
    database = current_app.config['GETTERS']['database']()
    data_points = database.data_points

    if not data_points:
        return render_template("table.html", table_data=[])

    latest_row = data_points[-1].to_dict()
    hidden = set(current_app.config.get('HIDDEN_DATA') or [])
    data_thesaurus = current_app.config.get('DATA_THESAURUS', {})

    # Filter + apply thesaurus in one loop
    filtered_row = {
        data_thesaurus.get(key, key): value
        for key, value in latest_row.items()
        if '/last_timestamp' not in key and key not in hidden
    }

    return render_template("table.html", table_data=[filtered_row])

@monitor_bp.route('/tiles/<int:z>/<int:x>/<int:y>.png')
def serve_tile(z, x, y):
    path = os.path.join(current_app.root_path, 'static', 'tiles', str(z), str(x), f"{y}.png")
    if os.path.exists(path):
        return send_file(path)
    else:
        abort(404)

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

