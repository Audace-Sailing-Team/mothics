import math
import time
import logging
from flask import Flask, render_template, jsonify, request, Response
from threading import Thread
from .database import Track
from .bokeh_plots import create_bokeh_plots
from .helpers import tipify, compute_status


class WebApp:
    def __init__(self, getters=None, setters=None, auto_refresh_table=2, logger_fname=None, rm_thesaurus=None, timeout_offline=60, timeout_noncomm=30):
        self.getters = getters
        self.setters = setters
        self.logger_fname = logger_fname
        self.app = Flask(__name__, template_folder="templates", static_folder='static')
        self.auto_refresh_table = auto_refresh_table*1000
        self.setup_routes()
        self.rm_thesaurus = rm_thesaurus
        self.timeout_offline = timeout_offline
        self.timeout_noncomm = timeout_noncomm
        
        # Setup logger
        self.logger = logging.getLogger("WebApp")
        # Ignore less than ERROR level logs from werkzeug
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        
    def setup_routes(self):
        @self.app.route("/")
        def index():
            database = self.getters['database']()
            # database = self.get_database()
            script, div = create_bokeh_plots(database)
            return render_template("index.html", script=script, div=div, auto_refresh=self.auto_refresh_table)
            
        @self.app.route("/get_table")
        def get_table():
            database = self.getters['database']()
            latest_data = [{key: value for key, value in database.data_points[-1].to_dict().items() if '/last_timestamp' not in key}] if database.data_points else []
            
            return render_template("table.html", table_data=latest_data)
        
        @self.app.route("/get_status")
        def get_status():
            # Fetch the latest aggregated data point from the database
            database = self.getters['database']()
            latest_data = database.data_points[-1].to_dict() if database.data_points else {}    
            now = latest_data['timestamp']
            # Compute status for each remote unit
            status_data = {rm.split('/')[0]: compute_status(ts, now=now, timeout_noncomm=self.timeout_noncomm, timeout_offline=self.timeout_offline) for rm, ts in latest_data.items() if 'last_timestamp' in rm}

            # Apply rm_thesaurus mapping if available
            if self.rm_thesaurus:
                status_data = {self.rm_thesaurus[rm]: status for rm, status in status_data.items()}
        
            return render_template("status.html", status_data=status_data)

        @self.app.route('/logs')
        def logs():
            return render_template('logs.html') #, log_data=log_data)
        
        @self.app.route('/stream_logs')
        def stream_logs():
            def generate():
                with open(self.logger_fname, 'r') as f:
                    while True:
                        line = f.readline()
                        if line:
                            yield f"data: {line}\n\n"
            return Response(generate(), content_type='text/event-stream')

        @self.app.route('/empty_log_file', methods=['POST'])
        def empty_log_file():
            try:
                open(self.logger_fname, 'w').close()
                return jsonify({'status': 'success', 'message': 'Log file emptied successfully.'}), 200
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500
        
        @self.app.route('/settings', methods=['GET', 'POST'])
        def settings():
            # Process settings here with form submission or any other logic
            if request.method == 'POST':
                # Update table refresh rate
                if request.form['auto_refresh_table']:
                    self.auto_refresh_table = tipify(request.form['auto_refresh_table'])*1000
                    self.logger.info(f'set auto refresh rate for table at {self.auto_refresh_table/1000} s')
                # Update Aggregator refresh rate
                if request.form['aggregator_interval']:
                    aggregator_refresh_rate = tipify(request.form['aggregator_interval'])
                    try:
                        self.setter['aggregator_refresh_rate'](aggregator_refresh_rate)
                        self.logger.info(f'set Aggregator refresh rate at {aggregator_refresh_rate} s')
                    except:
                        self.logger.warning(f'could not set Aggregator refresh rate')
                # ADD OTHER TOGGLES HERE
                # Update settings
                return render_template('settings.html', success=True)
            return render_template('settings.html', success=False)
        
    def run(self, host="0.0.0.0", port=5000, debug=False):
        self.app.run(host=host, port=port, debug=debug)

    def start_in_background(self, host="0.0.0.0", port=5000, debug=False):
        thread = Thread(target=self.run, kwargs={"host": host, "port": port, "debug": debug})
        thread.daemon = True
        thread.start()
