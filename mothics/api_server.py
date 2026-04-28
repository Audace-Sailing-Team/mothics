from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from .system_manager import SystemManager

system_manager = SystemManager()

class API(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            status = system_manager.get_status()
            self._send_json(status or {})
        else:
            self._send_json({"error": "not found"}, code=404)

    def do_POST(self):
        if self.path == "/api/start":
            system_manager.start_live()
            self._send_json({"status": "ok"})
        elif self.path == "/api/stop":
            system_manager.stop()
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, code=404)

    def _send_json(self, data, code=200):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

def run():
    server = HTTPServer(("0.0.0.0", 8080), API)
    server.serve_forever()
