#!/usr/bin/env python3
import json
import os
import time
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
import toml

from .system_manager import SystemManager

system = None

def set_system_manager(sm):
    global system
    system = sm


# TODO: Consider using system.config_file directly once available
CONFIG_FILE = system.config_file if hasattr(system, 'config_file') else "config.toml"

# Static files directory (web_ui folder)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "web_ui")


class API(BaseHTTPRequestHandler):
    """
    HTTP API server for Mothics system control.
    All endpoints are explicit and type-safe.
    Static files are served from web_ui directory.
    """

    # ---------------------------
    # Utility
    # ---------------------------
    def _send(self, data, code=200):
        """Send JSON response."""
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path, content):
        """Send file response with appropriate MIME type."""
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self):
        """Read and parse JSON from request body."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def _serve_static_file(self, path):
        """Serve a static file from web_ui directory."""
        # Default to index.html for root
        if path == "/" or path == "":
            path = "index.html"

        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))

        # Security: ensure file is within STATIC_DIR
        file_path = os.path.abspath(file_path)
        if not file_path.startswith(os.path.abspath(STATIC_DIR)):
            self._send({"error": "forbidden"}, 403)
            return True

        # Check if file exists
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            self._send({"error": "not found"}, 404)
            return True

        # Serve the file
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self._send_file(file_path, content)
            return True
        except Exception as e:
            self._send({"error": str(e)}, 500)
            return True

    # ---------------------------
    # GET
    # ---------------------------
    def do_GET(self):
        """Handle GET requests."""
        path = self.path.split("?")[0]  # Remove query parameters

        # ---- API ENDPOINTS ----
        if path == "/api/status":
            self._send(system.get_status())
            return

        if path == "/api/sensors":
            self._send(system.get_sensors_status())
            return

        if path == "/api/config":
            self._send(system.get_config_view())
            return

        if path == "/api/log":
            log_file = system.config["files"]["logger_fname"]
            if os.path.exists(log_file):
                with open(log_file) as f:
                    self._send({"log": f.read()})
            else:
                self._send({"log": ""})
            return

        if path == "/api/data":
            if system.aggregator:
                track = system.track.get_current()
                points = [dp.to_dict() for dp in track.data_points]
                self._send({"data": points})

            else:
                self._send({"error": "aggregator not running"}, 400)
            return

        if path == "/api/monitor":
            data = {
                "status": system.get_status(),
                "current_data": system.track.get_current() if system.track else None
            }
            self._send(data)
            return

        if path == "/api/database/list":
            track_dir = system.config["files"]["output_dir"]
            files = [f for f in os.listdir(track_dir) if f.endswith(".json")]
            self._send({"tracks": files})
            return

        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                while True:
                    # Serve solo se il Communicator è attivo
                    if system and system.communicator:
                        raw = system.communicator.raw_data

                        # Convertiamo i timestamp in stringhe
                        safe_raw = {}
                        for topic, values in raw.items():
                            safe_raw[topic] = [
                                {str(ts): val} for entry in values for ts, val in entry.items()
                            ]

                        payload = json.dumps(safe_raw)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()

                    time.sleep(1)  # 10 Hz
            except Exception:
                return



        # ---- STATIC FILES ----
        # Serve static files from web_ui
        if self._serve_static_file(path):
            return

        # Default 404
        self._send({"error": "not found"}, 404)

    # ---------------------------
    # POST
    # ---------------------------
    def do_POST(self):
        """Handle POST requests."""
        path = self.path

        # ---- START ----
        if path == "/api/start":
            body = self._read_json()
            mode = body.get("mode", "live")
            track = body.get("track")

            try:
                if mode == "live":
                    system.start_live()
                elif mode == "replay":
                    system.start_replay(track_file=track)
                else:
                    self._send({"error": "invalid mode"}, 400)
                    return

                self._send({"status": "ok"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- STOP ----
        if path == "/api/stop":
            try:
                system.stop()
                self._send({"status": "ok"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- RESTART ----
        if path == "/api/restart":
            body = self._read_json()
            reload_cfg = body.get("reload_config", False)

            try:
                system.restart(reload_config=reload_cfg)
                self._send({"status": "ok"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- LOG: CLEAR ----
        if path == "/api/log/clear":
            try:
                log_file = system.config["files"]["logger_fname"]
                if os.path.exists(log_file):
                    with open(log_file, "w") as f:
                        pass
                    self._send({"status": "log cleared"})
                else:
                    self._send({"error": "log file not found"}, 404)
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- SAVE: START ----
        if path == "/api/save/start":
            try:
                system.track.start_run()
                self._send({"status": "saving started"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- SAVE: STOP ----
        if path == "/api/save/stop":
            try:
                system.track.end_run()
                self._send({"status": "saving stopped"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- CONFIG: UPDATE ----
        if path == "/api/config/update":
            try:
                new_cfg = self._read_json()

                # Merge shallow
                for k, v in new_cfg.items():
                    system.config_file_data[k] = v
                    system.load_config()  # rigenera system.config

                self._send({"status": "updated", "config": system.config})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- CONFIG: SAVE ----
        if path == "/api/config/save":
            try:
                with open(CONFIG_FILE, "w") as f:
                    toml.dump(system.config_file_data, f)
                self._send({"status": "saved"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- AGGREGATOR: SET INTERVAL ----
        if path == "/api/aggregator/interval":
            body = self._read_json()
            interval = body.get("interval")

            try:
                if system.aggregator:
                    system.aggregator.set_interval(interval)
                    self._send({"status": "ok"})
                else:
                    self._send({"error": "aggregator not running"}, 400)
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # ---- DATABASE: SELECT TRACK ----
        if path == "/api/database/select":
            body = self._read_json()
            index = body.get("index")

            try:
                track_dir = system.config["files"]["output_dir"]
                files = sorted([f for f in os.listdir(track_dir) if f.endswith(".json")])
                fname = files[int(index)]
                system.track.load(os.path.join(track_dir, fname))
                self._send({"metadata": {"file": fname}})

                # self._send({"metadata": meta})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        # Default 404
        self._send({"error": "not found"}, 404)

    def log_message(self, format, *args):
        """Suppress default logging to console."""
        pass


from http.server import ThreadingHTTPServer

def run():
    server = ThreadingHTTPServer(("0.0.0.0", 8081), API)
    print("API server running on port 8081")
    print(f"Static files served from: {STATIC_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    run()
