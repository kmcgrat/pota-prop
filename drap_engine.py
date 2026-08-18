import logging
import threading
import time
import urllib.request
from typing import List

logger = logging.getLogger(__name__)

class DrapEngine:
    """
    Retrieves and parses the NOAA SWPC D-Region Absorption Prediction (D-RAP) model.
    The HAF (Highest Affected Frequency for 1 dB absorption) is provided in a grid.
    Attenuation at any frequency f can be estimated as: A(f) = (HAF / f)^2 dB.
    """
    def __init__(self, fetch_interval_sec=900):
        self.fetch_interval_sec = fetch_interval_sec
        self._lock = threading.Lock()
        self.haf_grid: List[List[float]] = []
        self.lats: List[float] = []
        self.lons: List[float] = []
        self.last_fetch_time: float = 0.0
        self.is_running = False
        self._thread = None
        self.error_message = None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_running = False

    def _fetch_loop(self):
        while self.is_running:
            try:
                self.fetch_drap_data()
            except Exception as e:
                logger.error(f"D-RAP fetch error: {e}")
                self.error_message = str(e)
            
            # Wait for next interval, checking periodically if we should stop
            for _ in range(self.fetch_interval_sec):
                if not self.is_running:
                    break
                time.sleep(1)

    def fetch_drap_data(self):
        url = "https://services.swpc.noaa.gov/text/drap_global_frequencies.txt"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "POTA-Hunter/26.8.17 (Amateur Radio Operator Tool)"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                text = response.read().decode('utf-8')
                self._parse_text(text)
                self.last_fetch_time = time.time()
                self.error_message = None

    def _parse_text(self, text: str):
        lines = text.splitlines()
        new_grid = []
        lats = []
        lons = None

        for line in lines:
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            
            # The longitude header row starts with spaces
            if '|' not in line:
                if not lons:
                    try:
                        parts = line.strip().split()
                        lons = [float(p) for p in parts]
                    except ValueError:
                        pass
                continue
            
            # Data rows: " 89 |  2.0  2.0 ..."
            try:
                parts = line.split('|')
                lat_val = float(parts[0].strip())
                val_strs = parts[1].split()
                vals = [float(v) for v in val_strs]
                
                if lons and len(vals) == len(lons):
                    lats.append(lat_val)
                    new_grid.append(vals)
            except ValueError:
                continue

        with self._lock:
            self.lats = lats
            if lons:
                self.lons = lons
            self.haf_grid = new_grid

    def get_haf(self, lat: float, lon: float) -> float:
        """Get Highest Affected Frequency (HAF) in MHz for the given coordinates."""
        with self._lock:
            if not self.haf_grid or not self.lats or not self.lons:
                return 0.0
            
            # Find closest lat index
            # lats are typically descending: 89, 87, ... -89
            closest_lat_idx = min(range(len(self.lats)), key=lambda i: abs(self.lats[i] - lat))
            
            # Find closest lon index
            closest_lon_idx = min(range(len(self.lons)), key=lambda i: abs(self.lons[i] - lon))
            
            return self.haf_grid[closest_lat_idx][closest_lon_idx]

    def get_attenuation_db(self, lat: float, lon: float, freq_mhz: float) -> float:
        """
        Estimate the non-deviative D-region absorption attenuation in dB.
        A(f) = (HAF / f)^2
        """
        if freq_mhz <= 0:
            return 0.0
        
        haf = self.get_haf(lat, lon)
        if haf <= 0.0:
            return 0.0
        
        return (haf / freq_mhz) ** 2


# Global singleton
_GLOBAL_DRAP_ENGINE = DrapEngine()
_GLOBAL_DRAP_ENGINE.start()

def get_drap_attenuation(lat: float, lon: float, freq_mhz: float) -> float:
    return _GLOBAL_DRAP_ENGINE.get_attenuation_db(lat, lon, freq_mhz)

def get_drap_haf(lat: float, lon: float) -> float:
    return _GLOBAL_DRAP_ENGINE.get_haf(lat, lon)

def get_drap_last_sync_time() -> float:
    return _GLOBAL_DRAP_ENGINE.last_fetch_time

def get_drap_status() -> str:
    if _GLOBAL_DRAP_ENGINE.error_message:
        return f"Error: {_GLOBAL_DRAP_ENGINE.error_message}"
    if _GLOBAL_DRAP_ENGINE.last_fetch_time == 0:
        return "Syncing..."
    
    elapsed = int(time.time() - _GLOBAL_DRAP_ENGINE.last_fetch_time)
    if elapsed < 60:
        return f"Synced {elapsed}s ago"
    return f"Synced {elapsed // 60}m ago"
