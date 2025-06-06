import secrets
import socket
import os
import requests
import time
import logging
from flask import Flask
from threading import Thread
from flask_compress import Compress
from tornado.log import access_log, app_log, gen_log
from waitress import serve

from .blueprints.bp_monitoring import monitor_bp
from .blueprints.bp_logging import log_bp
from .blueprints.bp_saving import save_bp
from .blueprints.bp_settings import settings_bp
from .blueprints.bp_database import database_bp


class WebApp:
    def __init__(self, getters=None, setters=None, auto_refresh_table=2, logger_fname=None, rm_thesaurus=None, data_thesaurus=None, hidden_data_cards=None, hidden_data_plots=None, timeout_offline=60, timeout_noncomm=30, track_manager=None, track_manager_directory=None, plot_mode='real-time', gps_tiles_directory=None, track_variable='speed', track_thresholds=None, track_colors=None, track_units=None, out_dir=None, instance_dir=None, system_manager=None, track_history_minutes=None):
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
        self.track_manager = track_manager
        """Database instance"""
        self.track_manager_directory = track_manager_directory
        """Database directory"""
        self.gps_tiles_directory = gps_tiles_directory
        """GPS tiles directory"""
        self.track_variable = track_variable
        """Variable which determines GPS track coloring"""
        self.track_thresholds = track_thresholds
        """Variable thresholds at which GPS track coloring changes"""
        self.track_colors = track_colors
        """Colors for GPS track"""
        self.track_units = track_units
        """Units of measurement for variable in GPS track"""
        self.out_dir = out_dir
        """Output directory"""
        self.instance_dir = instance_dir
        """Main process directory"""
        self.track_history_minutes = track_history_minutes
        """Track history length in minutes"""
        
        # Setup logger
        self.setup_logging()
        
        # Create the Flask app
        self.app = Flask(__name__, template_folder="templates", static_folder='static')

        # Compress responses 
        Compress(self.app)
        
        # Pass configuration to the app so blueprints can access it
        self.app.config.update({
            'GETTERS': self.getters,
            'SETTERS': self.setters,
            'INSTANCE_DIRECTORY': self.instance_dir,
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
            'GPS_TILES_DIRECTORY': self.gps_tiles_directory,
            'TRACK_VARIABLE': self.track_variable,
            'TRACK_THRESHOLDS': self.track_thresholds,
            'TRACK_COLORS': self.track_colors,
            'TRACK_UNITS': self.track_units,
            'GPS_HISTORY_MINUTES': self.track_history_minutes,
            'SYSTEM_MGR': system_manager
        })
        
        # Setup secret key
        self.setup_secret_key()
            
        # Setup routes
        self.setup_routes()
        
    def setup_logging(self):
        # Silence Waitress
        logging.getLogger("waitress").setLevel(logging.ERROR)
        
        # Silence Tornado
        for tlog in [access_log, app_log, gen_log]:
            tlog.setLevel(logging.ERROR)
            tlog.propagate = False

        # Silence werkzeug
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        # Create the main logger
        self.logger = logging.getLogger("WebApp")
        self.logger.setLevel(logging.DEBUG)

    def setup_secret_key(self):
        """
        Configure a secure secret key for Flask sessions and security.
        
        Priority for secret key sources:
        1. Environment variable (most secure)
        2. Instance-specific file
        3. Generated secure random key (fallback)
        """
        # Get path
        instance_path = os.path.join(self.out_dir, 'instance')
        os.makedirs(instance_path, exist_ok=True)
        secret_key_path = os.path.join(instance_path, 'secret_key')

        # Try environment variable first
        secret_key = os.environ.get('FLASK_SECRET_KEY')

        # If no environment variable, try reading from file
        if not secret_key and os.path.exists(secret_key_path):
            with open(secret_key_path, 'r') as f:
                secret_key = f.read().strip()

        # If no existing key, generate a new one
        if not secret_key:
            secret_key = secrets.token_hex(32)  # 256-bit key
            
            # Save generated key to file for persistence
            with open(secret_key_path, 'w') as f:
                f.write(secret_key)
            
            # Secure the file
            os.chmod(secret_key_path, 0o600)  # Read/write for owner only

        # Configure the app with the secret key
        self.app.secret_key = secret_key

        # Additional security configurations
        self.app.config.update(
            SESSION_COOKIE_SECURE=True,  # Only send cookie over HTTPS
            SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript access to session cookie
            SESSION_COOKIE_SAMESITE='Lax',  # Protect against CSRF
        )
        
    def setup_routes(self):
        # Register the monitoring blueprint (and others if created)
        self.app.register_blueprint(monitor_bp)
        self.app.register_blueprint(settings_bp)
        self.app.register_blueprint(log_bp)
        self.app.register_blueprint(save_bp)
        self.app.register_blueprint(database_bp)

    def run_developement(self, host="0.0.0.0", port=5000, debug=False):
        """
        Start the integrated Werkzeug server for developement.
        """
        self.process = Thread(target=self.app.run, kwargs={"host": host, "port": port, "debug": debug, "use_reloader": False}, name='webapp')
        self.process.daemon = True
        self.process.start()
        
    def serve(self, host="0.0.0.0", port=5000):
        serve(self.app, host=host, port=port)
