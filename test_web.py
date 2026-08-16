import unittest
import os
import json
import urllib.request
import urllib.error
import tempfile
import shutil

from map_server import MapServerManager, MapHTTPRequestHandler

class TestMapServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.map_file = os.path.join(self.temp_dir, "map.html")
        with open(self.map_file, "w") as f:
            f.write("<html><body>Test Map</body></html>")
            
        self.server_mgr = MapServerManager(self.temp_dir)
        self.server_mgr.start()
        
    def tearDown(self):
        self.server_mgr.stop()
        shutil.rmtree(self.temp_dir)

    def test_serve_html_with_valid_token(self):
        url = self.server_mgr.get_url()
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            content = response.read().decode('utf-8')
            self.assertIn("Test Map", content)

    def test_serve_html_forbidden_without_token(self):
        url = f"http://127.0.0.1:{self.server_mgr.port}/map.html"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 403)

    def test_api_map_data(self):
        self.server_mgr.update_data("home_lat", 42.0)
        self.server_mgr.update_data("home_lon", -71.0)
        
        url = f"http://127.0.0.1:{self.server_mgr.port}/api/map_data?token={self.server_mgr.token}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode('utf-8'))
            self.assertEqual(data["home_lat"], 42.0)
            self.assertEqual(data["home_lon"], -71.0)

    def test_api_set_filter(self):
        callback_called = []
        def on_filter(band, mode, grayline):
            callback_called.append((band, mode, grayline))
            
        self.server_mgr.set_filter_callback(on_filter)
        
        url = f"http://127.0.0.1:{self.server_mgr.port}/api/set_filter?band=40m&mode=CW&grayline=true&token={self.server_mgr.token}"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0], ("40m", "CW", True))

if __name__ == '__main__':
    unittest.main()
