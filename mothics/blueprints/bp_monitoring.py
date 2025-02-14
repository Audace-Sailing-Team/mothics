from flask import Blueprint, render_template, jsonify, request, Response, current_app
from bokeh.embed import server_document
from ..bokeh_plots import create_bokeh_plots
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
    latest_data = [{key: value for key, value in database.data_points[-1].to_dict().items() if '/last_timestamp' not in key}] if database.data_points else []
    return render_template("table.html", table_data=latest_data)

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

