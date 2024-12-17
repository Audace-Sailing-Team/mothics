from flask import Flask, render_template, jsonify, request
from threading import Thread
from .database import Database
from .bokeh_plots import create_bokeh_plots

class WebApp:
    def __init__(self, database_getter=None, status_getter=None, auto_refresh_table=2):
        self.get_database = database_getter
        self.get_status = status_getter
        self.app = Flask(__name__, template_folder="templates", static_folder='static')
        self.auto_refresh_table = auto_refresh_table*1000
        self.setup_routes()
        
    def setup_routes(self):
        @self.app.route("/")
        def index():
            database = self.get_database()
            script, div = create_bokeh_plots(database)
            return render_template("index.html", script=script, div=div, auto_refresh=self.auto_refresh_table)
            
        @self.app.route("/get_table")
        def get_table():
            self.database = self.get_database()
            latest_data = [self.database.data_points[-1].to_dict()] if self.database.data_points else []
            return render_template("table.html", table_data=latest_data)
        
        @self.app.route("/get_status")
        def get_status():
            self.status = self.get_status()
            return render_template("status.html", status_data=self.status)

        @self.app.route('/logs')
        def logs():
            # For now, let's simulate logs being read from a file or database
            log_data = ["Log entry 1", "Log entry 2", "Log entry 3"]
            return render_template('logs.html', log_data=log_data)

        @self.app.route('/settings', methods=['GET', 'POST'])
        def settings():
            # Process settings here with form submission or any other logic
            if request.method == 'POST':
                # Process form data and apply settings
                new_setting = request.form['setting']
                # Update settings
                return render_template('settings.html', success=True)
            return render_template('settings.html', success=False)

    def run(self, host="0.0.0.0", port=5000, debug=False):
        self.app.run(host=host, port=port, debug=debug)

    def start_in_background(self, host="0.0.0.0", port=5000, debug=False):
        thread = Thread(target=self.run, kwargs={"host": host, "port": port, "debug": debug})
        thread.daemon = True
        thread.start()
