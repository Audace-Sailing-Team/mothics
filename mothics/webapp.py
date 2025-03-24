import socket
import os
import requests
import time
import logging
from flask import Flask
from threading import Thread
from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from tornado.log import access_log, app_log, gen_log

from .bokeh_plots import create_realtime_bokeh_app
from .blueprints.bp_monitoring import monitor_bp
from .blueprints.bp_logging import log_bp
from .blueprints.bp_saving import save_bp
from .blueprints.bp_settings import settings_bp
from .blueprints.bp_database import database_bp


class WebApp:
    def __init__(self, getters=None, setters=None, auto_refresh_table=2, logger_fname=None, rm_thesaurus=None, data_thesaurus=None, hidden_data_cards=None, hidden_data_plots=None, timeout_offline=60, timeout_noncomm=30, track_manager_directory=None, plot_mode='real-time', gps_tiles_directory=None):
        self.getters = getters or {}
        """Getter methods from other Mothics components"""
        self.setters = setters or {}
        """Setter methods for settings, etc..."""
        self.logger_fname = logger_fname
        """Logger filename"""
        self.auto_refresh_table = auto_refresh_table * 1000  # milliseconds
        """Auto refresh interval for the data cards (and the whole dashboard)"""
        self.rm_thesaurus = rm_thesaurus
        """Aliases for remote unit names"""
        self.data_thesaurus = data_thesaurus
        """Aliases for sensor data names"""
        self.hidden_data_cards = hidden_data_cards
        """Sensor data addresses hidden from card view"""
        self.hidden_data_plots = hidden_data_plots
        """Sensor data addresses hidden from plot view"""
        self.timeout_offline = timeout_offline
        """Threshold to set remote unit as offline"""
        self.timeout_noncomm = timeout_noncomm
        """Threshold to set remote unit as non communicative"""
        self.track_manager_directory = track_manager_directory
        """Database directory"""
        self.gps_tiles_directory = gps_tiles_directory
        """GPS tiles directory"""
        self.plot_mode = plot_mode
        """Data plot mode - `static` or `real-time`"""
        self.track_manager = None
        
        # Setup logger
        self.setup_logging()

        # Get bokeh url
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        self.plot_realtime_url = f"http://{hostname}.local:5006/bokeh_app"
        """Real-time bokeh server URL"""        
        
        # Create the Flask app
        self.app = Flask(__name__, template_folder="templates", static_folder='static')
        
        # Pass configuration to the app so blueprints can access it
        self.app.config.update({
            'GETTERS': self.getters,
            'SETTERS': self.setters,
            'AUTO_REFRESH_TABLE': self.auto_refresh_table,
            'RM_THESAURUS': self.rm_thesaurus,
            'DATA_THESAURUS': self.data_thesaurus,
            'HIDDEN_DATA_CARDS': self.hidden_data_cards,
            'HIDDEN_DATA_PLOTS': self.hidden_data_plots,
            'TIMEOUT_OFFLINE': self.timeout_offline,
            'TIMEOUT_NONCOMM': self.timeout_noncomm,
            'LOGGER_FNAME': self.logger_fname,
            'TRACK_MANAGER_DIRECTORY': self.track_manager_directory,
            'TRACK_MANAGER': self.track_manager,
            'LOGGER': self.logger,
            'PLOT_MODE': self.plot_mode,
            'PLOT_REALTIME_URL': self.plot_realtime_url,
            'GPS_TILES_DIRECTORY': self.gps_tiles_directory
        })
        
        # Start bokeh server
        self.bokeh_server = None
        self.bokeh_thread = None

        self.allowed_origins = [
            "localhost:5000", "127.0.0.1:5000",
            f"{hostname}:5000", f"{local_ip}:5000",
            "localhost:5006", "127.0.0.1:5006",
            f"{hostname}:5006", f"{local_ip}:5006",
            "mothics.local:5000", "mothics.local:5006"
        ]

        if self.plot_mode == "real-time":
            self.start_bokeh_server()
    
        # Setup routes
        self.setup_routes()

    def setup_logging(self):
        # Silence Tornado
        for tlog in [access_log, app_log, gen_log]:
            tlog.setLevel(logging.ERROR)
            tlog.propagate = False

        # Silence Bokeh
        for name in ["bokeh", "bokeh.server", "bokeh.server.server"]:
            logger = logging.getLogger(name)
            logger.handlers.clear()              
            logger.setLevel(logging.ERROR)
            logger.propagate = False

        # Silence werkzeug
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        # Create the main logger
        self.logger = logging.getLogger("WebApp")
        self.logger.setLevel(logging.DEBUG)

    def start_bokeh_server(self):
        """Launches the Bokeh server in a new thread."""
        if self.bokeh_thread is not None:
            self.logger.warning("Bokeh server already running.")
            return

        def bokeh_server_thread():
            try:
                database_instance = self.getters["database"]()
                app = Application(FunctionHandler(
                    lambda doc: create_realtime_bokeh_app(
                        doc,
                        database_instance,
                        hidden_data=self.hidden_data_plots,
                        data_thesaurus=self.data_thesaurus
                    )
                ))

                self.bokeh_server = Server(
                    {"/bokeh_app": app},
                    port=5006,
                    allow_websocket_origin=self.allowed_origins,
                    address="0.0.0.0"
                )

                self.bokeh_server.start()
                self.logger.info("Bokeh server started.")
                self.bokeh_server.io_loop.start()
            except Exception as e:
                self.logger.error(f"Bokeh server failed to start: {e}")

        self.bokeh_thread = Thread(target=bokeh_server_thread)
        self.bokeh_thread.daemon = True
        self.bokeh_thread.start()

    def stop_bokeh_server(self):
        """Stops the running Bokeh server cleanly."""
        if not self.bokeh_server:
            self.logger.warning("No Bokeh server to stop.")
            return

        def shutdown():
            try:
                self.bokeh_server.stop()
                self.logger.info("Bokeh server stopped.")
                self.bokeh_server.io_loop.stop()
            except Exception as e:
                self.logger.error(f"Error while stopping Bokeh server: {e}")

        try:
            self.bokeh_server.io_loop.add_callback(shutdown)
            self.bokeh_thread.join(timeout=2)
        except Exception as e:
            self.logger.error(f"Failed to join Bokeh thread: {e}")
        finally:
            self.bokeh_server = None
            self.bokeh_thread = None

    def restart_bokeh_server(self):
        """Restarts the Bokeh server."""
        self.logger.info("Restarting Bokeh server...")
        self.stop_bokeh_server()
        time.sleep(1)  # Give time for port to release
        self.start_bokeh_server()

        
    def setup_routes(self):
        # Register the monitoring blueprint (and others if created)
        self.app.register_blueprint(monitor_bp)
        self.app.register_blueprint(settings_bp)
        self.app.register_blueprint(log_bp)
        self.app.register_blueprint(save_bp)
        self.app.register_blueprint(database_bp)

    def run(self, host="0.0.0.0", port=5000, debug=False):
        self.process = Thread(target=self.app.run, kwargs={"host": host, "port": port, "debug": debug, "use_reloader": False})
        self.process.daemon = True
        self.process.start()
