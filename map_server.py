import os
import json
import logging
import threading
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    pass

class MapHTTPRequestHandler(BaseHTTPRequestHandler):
    auth_token = ""
    resources_dir = ""
    map_data = {
        "home_lat": 38.3125,
        "home_lon": -81.7083,
        "spots": [],
        "heatmap": [],
        "band": "20m",
        "mode": "SSB",
        "grayline": [],
        "last_update": "N/A",
        "lightning": []
    }
    
    # Callback to signal the main PyQt app that a filter changed
    on_filter_changed_cb = None

    def log_message(self, format, *args):
        # Suppress standard logging to stdout to keep terminal output clean
        pass
        
    def _send_cors_headers(self):
        # Allow requests from localhost
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-type, X-Map-Token')

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        token = query.get("token", [""])[0]
        req_token = self.headers.get("X-Map-Token") or token

        if path == "/api/map_data":
            if req_token != self.auth_token:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(self.map_data).encode("utf-8"))
            return

        if path == "/api/set_filter":
            if req_token != self.auth_token:
                self.send_response(403)
                self.end_headers()
                return
                
            band = query.get("band", [""])[0]
            mode = query.get("mode", [""])[0]
            grayline_str = query.get("grayline", ["false"])[0].lower()
            show_grayline = grayline_str == "true"
            
            if MapHTTPRequestHandler.on_filter_changed_cb:
                # Trigger callback in main thread
                # This could be called from another thread, but PyQt handles signal emissions fine.
                MapHTTPRequestHandler.on_filter_changed_cb(band, mode, show_grayline)
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        # Serve static map.html file
        if path in ("/", "/map.html"):
            if token != self.auth_token:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden: Invalid or missing token.")
                return

            file_path = os.path.join(self.resources_dir, "map.html")
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

class MapServerManager:
    def __init__(self, resources_dir: str):
        self.resources_dir = resources_dir
        self.token = secrets.token_hex(16)
        self.port = 0
        self.server = None
        self.thread = None
        
        MapHTTPRequestHandler.auth_token = self.token
        MapHTTPRequestHandler.resources_dir = resources_dir

    def set_filter_callback(self, cb):
        MapHTTPRequestHandler.on_filter_changed_cb = cb

    def start(self):
        self.server = ThreadedHTTPServer(("127.0.0.1", 0), MapHTTPRequestHandler)
        self.port = self.server.server_address[1]
        
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Local secure MapServer started on http://127.0.0.1:{self.port} with token {self.token}")

    def get_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def update_data(self, key: str, value):
        MapHTTPRequestHandler.map_data[key] = value

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
