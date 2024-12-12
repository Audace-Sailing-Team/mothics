from flask import Flask, render_template, jsonify
from threading import Thread
from .database import Database
from .bokeh_plots import create_bokeh_plots


class WebApp:
    def __init__(self, database_getter=None, auto_refresh_table=2):
        self.get_database = database_getter
        self.app = Flask(__name__, template_folder="templates")
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

        @self.app.route("/get_plots")
        def get_plots():
            self.database = self.get_database()
            plot_script, plot_div = create_bokeh_plots(self.database)
            return render_template("plots.html", plot_script=plot_script, plot_div=plot_div)
        
    def run(self, host="0.0.0.0", port=5000, debug=False):
        self.app.run(host=host, port=port, debug=debug)

    def start_in_background(self, host="0.0.0.0", port=5000, debug=False):
        thread = Thread(target=self.run, kwargs={"host": host, "port": port, "debug": debug})
        thread.daemon = True
        thread.start()
