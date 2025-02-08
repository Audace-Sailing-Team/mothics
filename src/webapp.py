import math
import time
import logging
from flask import Flask, render_template, jsonify, request, Response
from threading import Thread
from .bokeh_plots import create_bokeh_plots
from .helpers import tipify, compute_status
from .database import Database

from .blueprints.bp_monitoring import monitor_bp
from .blueprints.bp_logging import log_bp
from .blueprints.bp_saving import save_bp
from .blueprints.bp_settings import settings_bp


class WebApp:
    def __init__(self, getters=None, setters=None, auto_refresh_table=2, logger_fname=None, 
                 rm_thesaurus=None, timeout_offline=60, timeout_noncomm=30):
        self.getters = getters or {}
        self.setters = setters or {}
        self.logger_fname = logger_fname
        self.auto_refresh_table = auto_refresh_table * 1000  # milliseconds
        self.rm_thesaurus = rm_thesaurus
        self.timeout_offline = timeout_offline
        self.timeout_noncomm = timeout_noncomm
        self.track_manager = None
        
        # Setup logger
        self.logger = logging.getLogger("WebApp")
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        
        # Create the Flask app
        self.app = Flask(__name__, template_folder="templates", static_folder='static')
        
        # Pass configuration to the app so blueprints can access it
        self.app.config.update({
            'GETTERS': self.getters,
            'SETTERS': self.setters,
            'AUTO_REFRESH_TABLE': self.auto_refresh_table,
            'RM_THESAURUS': self.rm_thesaurus,
            'TIMEOUT_OFFLINE': self.timeout_offline,
            'TIMEOUT_NONCOMM': self.timeout_noncomm,
            'LOGGER_FNAME': self.logger_fname,
            'LOGGER': self.logger
        })
        
        self.setup_routes()
        
    def setup_routes(self):
        # Register the monitoring blueprint (and others if created)
        self.app.register_blueprint(monitor_bp)
        self.app.register_blueprint(settings_bp)
        self.app.register_blueprint(log_bp)
        self.app.register_blueprint(save_bp)
        # self.app.register_blueprint(control_bp, url_prefix='/control')
        
    def run(self, host="0.0.0.0", port=5000, debug=False):
        self.app.run(host=host, port=port, debug=debug)

    def start_in_background(self, host="0.0.0.0", port=5000, debug=False):
        thread = Thread(target=self.run, kwargs={"host": host, "port": port, "debug": debug})
        thread.daemon = True
        thread.start()
