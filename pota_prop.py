#!/usr/bin/env python3
"""
POTA Prop
A modern desktop GUI application for amateur radio operators hunting Parks on the Air.
Compares your hunted parks history against live POTA active spots.
"""

import csv
import os
import sys
import time
import json
import socket
import webbrowser
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from map_server import MapServerManager
from drap_engine import get_drap_status, get_drap_last_sync_time

APP_VERSION = "26.8.17-8"

MAP_RENDER_AUTO = "auto"
MAP_RENDER_QT = "qt"
MAP_RENDER_BROWSER = "browser"

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def is_chromebook_crostini() -> bool:
    """Detect if running inside ChromeOS / Crostini Linux container."""
    if os.path.exists('/proc/version'):
        try:
            with open('/proc/version', 'r') as f:
                content = f.read().lower()
                if 'cros-kernel' in content or 'chromium.org' in content:
                    return True
        except Exception:
            pass
    try:
        if socket.gethostname() == 'penguin':
            return True
    except Exception:
        pass
    return False


def open_map_browser(url: str):
    """
    Launch the Live Map in the system web browser or a dedicated frameless app window.
    Supports Chrome, Chromium, Brave, Microsoft Edge, and standard default browsers.
    """
    import subprocess
    import shutil
    import platform
    import os
    import tempfile
    import webbrowser
    import logging

    system = platform.system()
    profile_dir = os.path.join(tempfile.gettempdir(), 'pota_map_profile')
    
    custom_env = os.environ.copy()
    if system != "Windows" and system != "Darwin":
        custom_env["GTK_THEME"] = "Adwaita:dark"
        if is_chromebook_crostini():
            custom_env["LIBGL_ALWAYS_SOFTWARE"] = "1"

    try:
        if system == "Windows":
            paths = [
                shutil.which("chrome"),
                shutil.which("msedge"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
            ]
            for path in paths:
                if path and os.path.exists(path):
                    subprocess.Popen([path, f"--app={url}", "--password-store=basic", f"--user-data-dir={profile_dir}", "--force-dark-mode"], env=custom_env)
                    return
        elif system == "Darwin":
            chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.exists(chrome_path):
                subprocess.Popen([chrome_path, f"--app={url}", "--password-store=basic", f"--user-data-dir={profile_dir}", "--force-dark-mode"], env=custom_env)
                return
        else:
            for exe in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "brave-browser", "microsoft-edge", "microsoft-edge-stable"]:
                exe_path = shutil.which(exe)
                if exe_path:
                    if "garcon" in os.path.realpath(exe_path).lower():
                        continue
                    subprocess.Popen([exe, f"--app={url}", "--password-store=basic", f"--user-data-dir={profile_dir}", "--force-dark-mode"], env=custom_env)
                    return
    except Exception as e:
        logging.error(f"Failed to open frameless app browser: {e}")

    # Fallback to standard default browser tab
    webbrowser.open(url)


from PyQt6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    Qt,
    QUrl,
    QThreadPool,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QShortcut,
    QPainter,
    QPen,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

from data_engine import (
    DEFAULT_HUNTER_CSV_PATH,
    ActiveSpot,
    ComparedSpot,
    HuntedPark,
    compare_active_spots,
    fetch_active_spots,
    fetch_park_info,
    load_hunter_csv,
    normalize_ref,
    fetch_hunter_parks_from_api,
    submit_spot_to_api,
)
from auth_engine import POTAAuthenticator
from lightning_engine import (
    RegionalLightningSummary,
    fetch_regional_lightning_summary,
    reset_lightning_engine_location,
    point_in_polygon,
)
from weather_engine import (
    WeatherForecastSummary,
    fetch_local_weather_summary,
)
from propagation_engine import (
    ANTENNA_PRESETS,
    DEFAULT_ANTENNA_TYPE,
    DEFAULT_HOME_GRID,
    DEFAULT_TX_POWER_WATTS,
    POWER_PRESETS,
    BandNoiseBreakdown,
    CallsignResolver,
    PropagationResult,
    SolarWeather,
    compute_band_noise_matrix,
    fetch_live_solar_weather,
    is_self_spot,
    maidenhead_to_latlon,
    calculate_qso_probability,
    RegionalPathMatrix,
)
from summary_engine import generate_propagation_summary


def calculate_grayline_polylines(zenith_deg=90.0):
    dt = datetime.now(timezone.utc)
    day = dt.timetuple().tm_yday
    fractional_day = dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    
    gamma = 2 * math.pi / 365.0 * (day - 1 + fractional_day)
    
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
            
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
                       
    tst = dt.hour * 60 + dt.minute + dt.second / 60.0 + eqtime
    # Sun moves west: at noon UTC, tst~720, sun_lon~0. At 18:00 UTC, tst~1080, sun_lon~-90.
    sun_lon = 180.0 - (tst / 4.0)
    
    z_rad = math.radians(zenith_deg)
    
    points1 = []
    points2 = []
    for lat in range(-89, 90, 2):
        lat_rad = math.radians(lat)
        num = math.cos(z_rad) - math.sin(lat_rad) * math.sin(decl)
        den = math.cos(lat_rad) * math.cos(decl)
        cos_ha = num / den
        
        if -1.0 <= cos_ha <= 1.0:
            ha_deg = math.degrees(math.acos(cos_ha))
            lon1 = ((sun_lon - ha_deg + 540) % 360) - 180
            lon2 = ((sun_lon + ha_deg + 540) % 360) - 180
            points1.append([lat, lon1])
            points2.append([lat, lon2])
            
    # Sort points1 ascending by lat, points2 descending by lat to form a continuous line
    points1.sort(key=lambda x: x[0])
    points2.sort(key=lambda x: x[0], reverse=True)
    all_points = points1 + points2
    
    segments = []
    current_segment = []
    for pt in all_points:
        if not current_segment:
            current_segment.append(pt)
        else:
            prev_lon = current_segment[-1][1]
            # Split segment if there's a large longitude jump (dateline wrap or pole artifact)
            if abs(pt[1] - prev_lon) > 90.0:
                segments.append(current_segment)
                current_segment = [pt]
            else:
                current_segment.append(pt)
    if current_segment:
        segments.append(current_segment)
        
    return segments


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #161b22;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}

QGroupBox {
    border: 1px solid #30363d;
    border-radius: 8px;
    margin-top: 10px;
    font-weight: bold;
    color: #58a6ff;
    padding-top: 15px;
    background-color: #1c2128;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
}

QLineEdit, QComboBox {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f0f6fc;
    selection-background-color: #1f6feb;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #58a6ff;
}

QPushButton {
    background-color: #21262d;
    border: 1px solid #363b42;
    border-radius: 6px;
    padding: 6px 14px;
    color: #c9d1d9;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#btnPrimary {
    background-color: #238636;
    border: 1px solid #2ea043;
    color: #ffffff;
}
QPushButton#btnPrimary:hover {
    background-color: #2ea043;
}

QPushButton#btnAccent {
    background-color: #1f6feb;
    border: 1px solid #388bfd;
    color: #ffffff;
}
QPushButton#btnAccent:hover {
    background-color: #388bfd;
}

QTableWidget {
    background-color: #0d1117;
    alternate-background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    gridline-color: #21262d;
    color: #e6edf3;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #21262d;
    color: #8b949e;
    font-weight: bold;
    padding: 7px;
    border: 1px solid #30363d;
    border-top: none;
    border-left: none;
}
QHeaderView::section:hover {
    background-color: #30363d;
    color: #f0f6fc;
}

QScrollBar:vertical {
    border: none;
    background: #0d1117;
    width: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #58a6ff;
}

QMenuBar {
    background-color: #161b22;
    color: #c9d1d9;
    border-bottom: 1px solid #21262d;
    padding: 2px 4px;
}
QMenuBar::item {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    color: #c9d1d9;
}
QMenuBar::item:selected {
    background-color: #21262d;
    color: #58a6ff;
}
QMenuBar::item:pressed {
    background-color: #30363d;
    color: #ffffff;
}

QMenu {
    background-color: #1c2128;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 0px;
    color: #e6edf3;
}
QMenu::item {
    padding: 6px 24px 6px 14px;
    border-radius: 4px;
    margin: 2px 4px;
    color: #c9d1d9;
}
QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background-color: #30363d;
    margin: 4px 8px;
}

QStatusBar {
    background-color: #0d1117;
    border-top: 1px solid #30363d;
    color: #8b949e;
}

QToolTip {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}
"""


class WorkedParksTracker(dict):
    """
    Dictionary mapping park_ref (str) -> worked_utc_date (YYYY-MM-DD str).
    Provides .add() and .discard() for backwards compatibility with set operations.
    """

    def add(self, ref: str, worked_date_utc: Optional[str] = None):
        if not ref:
            return
        r = str(ref).strip().upper()
        d = worked_date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self[r] = d

    def discard(self, ref: str):
        if not ref:
            return
        self.pop(str(ref).strip().upper(), None)


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom TableWidgetItem that sorts numerically instead of alphabetically."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)


def format_muf_telemetry(prop: Optional[PropagationResult]) -> str:
    """Formats category-specific MUF and ray-mode telemetry for tooltips and spot intelligence displays."""
    if prop is None:
        return "N/A"
    if prop.spot_evidence and prop.spot_evidence.is_qrt:
        return "0.0 MHz (Activator QRT / Off Air)"
    path_type = prop.path_type or ""
    if "VHF" in path_type or "Horizon" in path_type:
        return "N/A (VHF Tropospheric Line-of-Sight)"
    if "Groundwave" in path_type or "Same Park" in path_type:
        return "N/A (Direct Groundwave / Co-located)"
    if "6m" in path_type or "Es" in path_type:
        if prop.muf_est_mhz >= 48.0:
            return "50.0 MHz (Summer Sporadic-E Skip Open)"
        else:
            return "28.0 MHz (6m Ionospheric Path Closed)"

    extra = []
    if prop.ray_mode and prop.ray_mode != "1F2":
        extra.append(f"Ray: {prop.ray_mode}")
    if prop.takeoff_angle_deg > 0:
        extra.append(f"Elev: {prop.takeoff_angle_deg:.1f}°")
    if prop.qrn_surge_db >= 6.0:
        extra.append(f"⚡ QRN +{prop.qrn_surge_db:.0f}dB")

    extra_str = f" [{', '.join(extra)}]" if extra else ""
    return f"{prop.muf_est_mhz:.1f} MHz{extra_str}"



class FetchPotaWorkerSignals(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)


class FetchPotaWorker(QRunnable):
    """Background worker to fetch live active spots."""

    def __init__(self):
        super().__init__()
        self.signals = FetchPotaWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            spots = fetch_active_spots(timeout=10)
            self.signals.finished.emit(spots)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class FetchSolarWorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class FetchSolarWorker(QRunnable):
    """Background worker to fetch NOAA solar weather."""

    def __init__(self):
        super().__init__()
        self.signals = FetchSolarWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            solar = fetch_live_solar_weather(timeout=10)
            self.signals.finished.emit(solar)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class FetchAuroraWorkerSignals(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)


class FetchAuroraWorker(QRunnable):
    """Background worker to fetch NOAA SWPC OVATION aurora model lines."""

    def __init__(self, force_refresh: bool = False):
        super().__init__()
        self.force_refresh = force_refresh
        self.signals = FetchAuroraWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            from aurora_engine import fetch_ovation_aurora_lines
            lines = fetch_ovation_aurora_lines(force_refresh=self.force_refresh)
            self.signals.finished.emit(lines)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class FetchLightningWorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class FetchLightningWorker(QRunnable):
    """Background worker to fetch regional lightning."""

    def __init__(self, home_lat: float, home_lon: float):
        super().__init__()
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.signals = FetchLightningWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            lightning = fetch_regional_lightning_summary(self.home_lat, self.home_lon, timeout=10)
            self.signals.finished.emit(lightning)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class PhysicsWorkerSignals(QObject):
    finished = pyqtSignal(list, object)
    error = pyqtSignal(str)

class PhysicsWorker(QRunnable):
    """Background worker to compute heavy RF propagation math for all spots without freezing the UI."""
    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.signals = PhysicsWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            from data_engine import compare_active_spots
            self.kwargs['fast_mode'] = False
            compared = compare_active_spots(**self.kwargs)
            matrix = getattr(compare_active_spots, "last_regional_matrix", None)
            self.signals.finished.emit(compared, matrix)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class FetchPSKWorkerSignals(QObject):
    finished = pyqtSignal(list)


class FetchPSKWorker(QRunnable):
    def __init__(self, rbn_node: str):
        super().__init__()
        self.rbn_node = rbn_node
        self.signals = FetchPSKWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            from psk_engine import fetch_psk_spots
            spots = fetch_psk_spots(self.rbn_node, max_age_minutes=15)
            self.signals.finished.emit(spots)
        except Exception:
            self.signals.finished.emit([])

class FetchActivatorPSKWorker(QRunnable):
    def __init__(self, activator_call: str):
        super().__init__()
        self.activator_call = activator_call
        self.signals = FetchPSKWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            from psk_engine import fetch_activator_psk_spots
            spots = fetch_activator_psk_spots(self.activator_call, max_age_minutes=15)
            self.signals.finished.emit(spots)
        except Exception:
            try:
                self.signals.finished.emit([])
            except RuntimeError:
                pass

class CallsignLookupWorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class CallsignLookupWorker(QRunnable):
    """Background worker to lookup operator callsign and Maidenhead grid."""

    def __init__(self, callsign: str):
        super().__init__()
        self.callsign = callsign
        self.signals = CallsignLookupWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            resolver = CallsignResolver()
            loc = resolver.lookup_user_callsign(self.callsign)
            if loc:
                self.signals.finished.emit(loc)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class ParkLookupWorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


class ParkLookupWorker(QRunnable):
    """Background worker to lookup park coordinates and grid from POTA API."""

    def __init__(self, reference: str, active_spots: Optional[List[ActiveSpot]] = None):
        super().__init__()
        self.reference = reference
        self.active_spots = active_spots or []
        self.signals = ParkLookupWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            info = fetch_park_info(self.reference, self.active_spots)
            if info:
                self.signals.finished.emit(info)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class FetchWeatherWorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class FetchWeatherWorker(QRunnable):
    """Background worker to fetch Open-Meteo local weather summary."""

    def __init__(self, lat: float, lon: float, location_name: Optional[str] = None, force_refresh: bool = False):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.location_name = location_name
        self.force_refresh = force_refresh
        self.signals = FetchWeatherWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            summary = fetch_local_weather_summary(self.lat, self.lon, location_name=self.location_name, force_refresh=self.force_refresh)
            if summary:
                self.signals.finished.emit(summary)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class StatCard(QFrame):
    """Modern dashboard stat metric card."""
    clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        value: str = "0",
        accent_color: str = "#58a6ff",
        parent=None,
        is_clickable: bool = False,
    ):
        super().__init__(parent)
        self.accent_color = accent_color
        self.is_clickable = is_clickable
        if is_clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"""
            StatCard {{
                background-color: #1c2128;
                border: 1px solid #30363d;
                border-left: 4px solid {accent_color};
                border-radius: 6px;
                padding: 3px 8px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("color: #8b949e; font-size: 9px; font-weight: 700;")
        layout.addWidget(self.lbl_title)

        self.lbl_value = QLabel(value)
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_size = "11px" if len(value) > 14 else "14px"
        self.lbl_value.setStyleSheet(
            f"color: {accent_color}; font-size: {font_size}; font-weight: 800;"
        )
        layout.addWidget(self.lbl_value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_value(self, val: str):
        val_str = str(val)
        self.lbl_value.setText(val_str)
        font_size = "12px" if len(val_str) > 14 else "16px"
        self.lbl_value.setStyleSheet(
            f"color: {self.accent_color}; font-size: {font_size}; font-weight: 800;"
        )

    def set_title(self, title: str):
        self.lbl_title.setText(str(title).upper())

    def set_accent_color(self, accent_color: str):
        self.accent_color = accent_color
        self.setStyleSheet(
            f"""
            StatCard {{
                background-color: #1c2128;
                border: 1px solid #30363d;
                border-left: 4px solid {accent_color};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            """
        )
        font_size = "12px" if len(self.lbl_value.text()) > 14 else "16px"
        self.lbl_value.setStyleSheet(
            f"color: {accent_color}; font-size: {font_size}; font-weight: 800;"
        )


class BandNoiseDialog(QDialog):
    """
    Dedicated modal dialog displaying real-time receiver noise floor and S-meter readings
    across all amateur radio bands (160m to 6m) modeled via ITU-R P.372, diurnal ionospheric
    solar elevation, and regional Blitzortung lightning telemetry.
    """

    def __init__(
        self,
        home_lat: float,
        home_lon: float,
        solar_weather: Optional[SolarWeather] = None,
        lightning_summary: Optional[RegionalLightningSummary] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.solar_weather = solar_weather or SolarWeather()
        self.lightning_summary = lightning_summary
        self.setWindowTitle("Amateur Band Receiver Noise Floor Matrix (ITU-R P.372 & Live QRN)")
        self.resize(1080, 700)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # 1. Header Banner
        header = QFrame()
        header.setStyleSheet(
            "background-color: #1c2128; border: 1px solid #30363d; border-radius: 8px; padding: 12px;"
        )
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)
        h_layout.setSpacing(6)

        title_lbl = QLabel("Receiver Noise Floor & ITU-R P.372 Band Matrix")
        title_lbl.setStyleSheet("color: #58a6ff; font-size: 18px; font-weight: 800;")
        h_layout.addWidget(title_lbl)

        # Telemetry summary line
        light_act = self.lightning_summary.get_activity_level() if self.lightning_summary else None
        light_txt = (
            f"<span style='color:{light_act.color}; font-weight:bold;'>Level {light_act.level} ({light_act.label})</span>"
            if light_act
            else "<span style='color:#8b949e;'>Inactive</span>"
        )
        light_dist = (
            f"Nearest: ~{self.lightning_summary.closest_storm_miles:.0f} mi"
            if self.lightning_summary and self.lightning_summary.closest_storm_miles is not None and self.lightning_summary.closest_storm_miles < 999.0
            else "No nearby storms"
        )

        sub_lbl = QLabel(
            f"<b>QTH:</b> {self.home_lat:.3f}°, {self.home_lon:.3f}° &nbsp;|&nbsp; "
            f"<b>Space Weather:</b> SFI {int(self.solar_weather.sfi)}, K={int(self.solar_weather.k_index)}, Flare: {self.solar_weather.xray_class} &nbsp;|&nbsp; "
            f"<b>⚡ Regional Lightning:</b> {light_txt} ({light_dist})"
        )
        sub_lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
        h_layout.addWidget(sub_lbl)
        layout.addWidget(header)

        # 2. Table of Noise Breakdown across Amateur Bands
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Band",
            "Frequency",
            "⚡ Atmospheric (QRN)",
            "Galactic (Space)",
            "Man-Made",
            "Total Noise (Fa)",
            "Noise Power (SSB)",
            "Est. S-Meter",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background-color: #0d1117;
                gridline-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #161b22;
                color: #8b949e;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #30363d;
                font-weight: 700;
            }
            QTableWidget::item {
                padding: 6px;
            }
            """
        )
        layout.addWidget(self.table)

        # 3. Explanatory Note Footer
        note_box = QFrame()
        note_box.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px;"
        )
        n_layout = QVBoxLayout(note_box)
        n_layout.setContentsMargins(6, 4, 6, 4)
        n_lbl = QLabel(
            "<b>Noise Modeling Notes:</b> "
            "• <b>Atmospheric (QRN)</b> models global diurnal ITU-R P.372 curves (night ducting vs day D-layer absorption) + live Blitzortung lightning surges (&le;750 mi). "
            "• <b>Galactic (Space)</b> models cosmic radio emission traversing the ionosphere. "
            "• <b>Man-Made</b> models quiet residential/rural baseline. "
            "• <b>S-Meter Calibration:</b> Standard IARU HF baseline (S9 = -73 dBm, 6 dB/S-unit, S0 = -127 dBm in 2.4 kHz SSB bandwidth)."
        )
        n_lbl.setWordWrap(True)
        n_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        n_layout.addWidget(n_lbl)
        layout.addWidget(note_box)

        # 4. Buttons
        btn_layout = QHBoxLayout()
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(
            """
            QPushButton {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #30363d;
                color: #ffffff;
            }
            """
        )
        btn_close.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        # Populate data
        self.populate_data()

    def populate_data(self):
        matrix = compute_band_noise_matrix(
            self.home_lat,
            self.home_lon,
            solar_weather=self.solar_weather,
            lightning_summary=self.lightning_summary,
        )
        self.table.setRowCount(len(matrix))

        for row, item in enumerate(matrix):
            # Band Name
            it_band = QTableWidgetItem(f"  {item.band}")
            it_band.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            it_band.setForeground(QColor("#58a6ff"))

            # Frequency
            it_freq = QTableWidgetItem(f"{item.freq_mhz:.3f} MHz")
            it_freq.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_freq.setForeground(QColor("#8b949e"))

            # Atmospheric
            if item.qrn_surge_db >= 1.0:
                atm_str = f"{item.f_atm_total_db:.1f} dB  (⚡ +{item.qrn_surge_db:.1f}dB)"
                col_atm = "#ffa657"
            else:
                atm_str = f"{item.f_atm_total_db:.1f} dB"
                col_atm = "#c9d1d9"
            it_atm = QTableWidgetItem(atm_str)
            it_atm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_atm.setForeground(QColor(col_atm))

            # Galactic
            it_gal = QTableWidgetItem(f"{item.f_gal_db:.1f} dB")
            it_gal.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_gal.setForeground(QColor("#bc8cff"))

            # Man-made
            it_man = QTableWidgetItem(f"{item.f_man_db:.1f} dB")
            it_man.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_man.setForeground(QColor("#8b949e"))

            # Total Fa
            it_fa = QTableWidgetItem(f"{item.f_a_total_db:.1f} dB")
            it_fa.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_fa.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            it_fa.setForeground(QColor("#f1e05a" if item.is_elevated_qrn else "#e6edf3"))

            # Noise Power
            it_pwr = QTableWidgetItem(f"{item.noise_power_dbm:.1f} dBm")
            it_pwr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_pwr.setForeground(QColor("#8b949e"))

            # S-Meter Badge
            if item.s_units_val >= 8.0:
                s_col = "#f85149" # Red
            elif item.s_units_val >= 4.0:
                s_col = "#ffa657" # Orange
            elif item.s_units_val >= 2.0:
                s_col = "#f1e05a" # Yellow
            else:
                s_col = "#7ee787" # Green

            it_smeter = QTableWidgetItem(f" {item.s_units_label} ")
            it_smeter.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            it_smeter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            it_smeter.setForeground(QColor(s_col))

            self.table.setItem(row, 0, it_band)
            self.table.setItem(row, 1, it_freq)
            self.table.setItem(row, 2, it_atm)
            self.table.setItem(row, 3, it_gal)
            self.table.setItem(row, 4, it_man)
            self.table.setItem(row, 5, it_fa)
            self.table.setItem(row, 6, it_pwr)
            self.table.setItem(row, 7, it_smeter)


class PropagationDiagramWindow(QDialog):
    def __init__(self, prop_result, cs=None, parent=None):
        super().__init__(parent)
        self.prop = prop_result
        self.cs = cs
        self.setWindowTitle("Propagation Diagram")
        self.resize(940, 620)
        self.setStyleSheet("background-color: #0d1117; color: #c9d1d9;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        painter.fillRect(self.rect(), QColor("#0d1117"))
        
        if not self.prop:
            painter.setPen(QColor("#8b949e"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No propagation data available.")
            return

        ground_y = h - 60
        scale_x = (w - 100) / max(10, self.prop.distance_km)
        scale_y = (h - 150) / max(300, 450)
        
        # Draw ground
        painter.setPen(QPen(QColor("#3fb950"), 2))
        painter.drawLine(50, ground_y, w - 50, ground_y)
        
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        
        hunter_call = "HUNTER"
        from PyQt6.QtCore import QSettings, QRectF
        settings = QSettings("POTA", "HunterComparator")
        my_call = str(settings.value("my_call", "")).strip().upper()
        if my_call:
            hunter_call = my_call
            
        activator_call = self.cs.spot.activator if self.cs and hasattr(self.cs, 'spot') else "ACTIVATOR"
        
        hunter_rect = QRectF(50 - 100, ground_y + 10, 200, 20)
        painter.drawText(hunter_rect, Qt.AlignmentFlag.AlignCenter, hunter_call)
        
        activator_x = 50 + self.prop.distance_km * scale_x
        activator_rect = QRectF(activator_x - 100, ground_y + 10, 200, 20)
        painter.drawText(activator_rect, Qt.AlignmentFlag.AlignCenter, activator_call)
        
        font.setBold(False)
        painter.setFont(font)
        
        # Draw layers (flat)
        if hasattr(self.prop, 'profile') and self.prop.profile:
            prof = self.prop.profile
            def draw_flat_layer(height_km, color, opacity, name):
                if opacity <= 0.05: return
                y = ground_y - height_km * scale_y
                painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), int(255*opacity)), 1, Qt.PenStyle.DashLine))
                painter.drawLine(50, int(y), w - 50, int(y))
                painter.setPen(QColor(color.red(), color.green(), color.blue(), 255))
                painter.drawText(50, int(y - 5), name)
            
            draw_flat_layer(75, QColor(255, 165, 0), max(0.2, prof.daylight_path), "D-Layer (75km - Absorption)")
            draw_flat_layer(prof.hmE, QColor(0, 191, 255), 0.6, f"E-Layer ({int(prof.hmE)}km)")
            draw_flat_layer(prof.hmF2, QColor(138, 43, 226), 0.9, f"F2-Layer ({int(prof.hmF2)}km - Refraction)")
        
        # Draw Ray
        if hasattr(self.prop, 'ray_candidate') and self.prop.ray_candidate:
            ray = self.prop.ray_candidate
            
            # If the physics model says it penetrated, but empirical evidence (local spots)
            # pushed the probability score high enough to be viable, force refraction on the diagram.
            empirically_viable = self.prop.probability_pct >= 40
            draw_as_penetrated = ray.is_penetrated and not empirically_viable
            
            painter.setPen(QPen(QColor("#f85149" if draw_as_penetrated else "#3fb950"), 3))
            
            hops = ray.hop_count
            dist_per_hop = self.prop.distance_km / hops
            path = QPainterPath()
            path.moveTo(50, ground_y)
            
            for i in range(hops):
                x_start = 50 + (i * dist_per_hop) * scale_x
                x_end = 50 + ((i + 1) * dist_per_hop) * scale_x
                x_mid = (x_start + x_end) / 2
                
                y_peak = ground_y - ray.virtual_height_km * scale_y
                
                if draw_as_penetrated:
                    tan_a = math.tan(math.radians(max(0.1, ray.takeoff_angle_deg)))
                    end_y = y_peak - 40
                    end_x = x_start + (ground_y - end_y) / (tan_a * scale_y / scale_x)
                    path.lineTo(end_x, end_y)
                    break
                else:
                    path.quadTo(x_mid, y_peak - (y_peak*0.1), x_end, ground_y)
            
            painter.drawPath(path)
            
            if ray.is_penetrated and empirically_viable:
                painter.setPen(QPen(QColor("#f85149"), 2, Qt.PenStyle.DashLine))
                dash_path = QPainterPath()
                dash_path.moveTo(50, ground_y)
                tan_a = math.tan(math.radians(max(0.1, ray.takeoff_angle_deg)))
                y_peak = ground_y - ray.virtual_height_km * scale_y
                end_y = y_peak - 40
                end_x = 50 + (ground_y - end_y) / (tan_a * scale_y / scale_x)
                dash_path.lineTo(end_x, end_y)
                painter.drawPath(dash_path)
            
            # Educational Text Summary
            painter.setPen(QColor("#c9d1d9"))
            solar = self.prop.solar_info
            freq_str = self.cs.frequency_mhz_str if self.cs else "?"
            band_str = self.cs.spot.band if self.cs else "?"
            text = (f"Frequency: {freq_str} ({band_str} {ray.mode_name})  |  "
                    f"Distance: {int(self.prop.distance_km)} km  |  Takeoff Angle: {ray.takeoff_angle_deg}°\n"
                    f"Solar Weather: SFI {int(solar.sfi)} | Kp {int(solar.k_index)} | Ap {int(solar.a_index)} | {solar.condition}\n\n")
            if draw_as_penetrated:
                text += "SKIP ZONE: Signal penetrated the ionosphere because the frequency is too high for the current F2 MUF.\n"
                text += "The activator is located inside your skip zone and cannot be heard via skywave."
            elif ray.is_penetrated and empirically_viable:
                is_lower_hf = False
                if self.cs and hasattr(self.cs, 'spot') and getattr(self.cs.spot, 'frequency_khz', 0) > 0:
                    is_lower_hf = self.cs.spot.frequency_khz < 14000.0
                else:
                    band_clean = str(band_str).lower().strip()
                    is_lower_hf = band_clean in ["160m", "80m", "60m", "40m", "30m", "160", "80", "60", "40", "30"]
                
                if is_lower_hf:
                    anomaly_cause = "Backscatter or NVIS anomaly"
                else:
                    anomaly_cause = "Sporadic-E (Es) or Chordal Hop"
                text += f"EMPIRICAL ANOMALY: Physics model predicted skip zone penetration, but local spotters confirm the path is open (likely {anomaly_cause}).\n"
            elif ray.is_screened_by_e:
                text += "E-LAYER SCREENING: Signal was blocked by a dense E-layer and could not reach the F2 layer."
            else:
                text += "SUCCESSFUL REFRACTION: Signal successfully bounced off the ionosphere to reach the target.\n"
                if hasattr(self.prop, 'profile') and self.prop.profile and self.prop.profile.daylight_path > 0.5:
                    text += "Note: Daytime solar radiation creates a D-layer, absorbing energy from your signal on lower frequencies.\n"

            if self.cs and getattr(self.cs, 'spot_evidence', None) and self.cs.spot_evidence.local_spotters:
                text += "\nLocal Spotters Hearing Activator:\n"
                for s in self.cs.spot_evidence.local_spotters[:4]:
                    meth = getattr(s, 'method', 'POTA Spot')
                    if getattr(s, 'snr', None) is not None:
                        meth += f" ({s.snr:+.0f}dB)"
                    dist = f"{int(s.distance_miles)}mi" if getattr(s, 'distance_miles', None) is not None else ""
                    text += f" • {s.callsign} [{meth}] {dist}\n"
                if len(self.cs.spot_evidence.local_spotters) > 4:
                    text += f" • ... and {len(self.cs.spot_evidence.local_spotters)-4} more local stations\n"
            
            from PyQt6.QtCore import QRectF
            rect = QRectF(50, 20, w - 100, 150)
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, text)


class SpotHistoryDialog(QDialog):
    """
    Detailed modal dialog showing live spot intelligence, empirical evidence breakdown,
    local spotter proximity, signal reports, and all historical respots.
    """

    def __init__(self, cs: ComparedSpot, home_lat: float, home_lon: float, parent=None):
        super().__init__(parent)
        self.cs = cs
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.setWindowTitle(
            f"Spot Intelligence & Respot Stream - {cs.spot.activator} @ {cs.spot.reference}"
        )
        self.resize(980, 740)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 1. Header Banner
        header = QFrame()
        header.setStyleSheet(
            "background-color: #1c2128; border: 1px solid #30363d; border-radius: 8px; padding: 6px;"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(6, 6, 6, 6)

        # Activator & Park details
        info_vbox = QVBoxLayout()
        lbl_act = QLabel(
            f"<span style='color:#58a6ff; font-size:15px; font-weight:800;'>{cs.spot.activator}</span> "
            f"<span style='color:#8b949e;'>at</span> "
            f"<span style='color:#f1e05a; font-size:14px; font-weight:700;'>{cs.spot.reference}</span>"
        )
        lbl_name = QLabel(
            f"<b>{cs.display_name}</b> - <span style='color:#8b949e;'>{cs.display_location}</span>"
        )
        lbl_dial = QLabel(
            f"Dial: <b>{cs.frequency_mhz_str}</b> ({cs.spot.mode} | {cs.spot.band}) | "
            f"Grid: <b>{cs.spot.grid6 or cs.spot.grid4 or 'N/A'}</b>"
        )
        info_vbox.addWidget(lbl_act)
        info_vbox.addWidget(lbl_name)
        info_vbox.addWidget(lbl_dial)
        h_layout.addLayout(info_vbox, stretch=1)

        # QSO Score badge card
        prob = cs.dx_percentage
        if prob >= 99:
            prob_color = "#FFD700"  # Gold - Exceptional
        elif prob >= 75:
            prob_color = "#3fb950"  # Green - Strong
        elif prob >= 50:
            prob_color = "#e3b341"  # Amber - Good
        elif prob >= 25:
            prob_color = "#db6d28"  # Orange - Fair
        else:
            prob_color = "#8b949e"  # Gray - Weak
        prob_card = QFrame()
        prob_card.setStyleSheet(
            f"background-color: #161b22; border: 2px solid {prob_color}; border-radius: 8px; padding: 4px 10px;"
        )
        prob_vbox = QVBoxLayout(prob_card)
        prob_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_p_title = QLabel("QSO SCORE")
        lbl_p_title.setStyleSheet("color: #8b949e; font-size: 9px; font-weight: bold;")
        score_text = f"{prob} !" if prob >= 99 else f"{prob}"
        lbl_p_val = QLabel(score_text)
        lbl_p_val.setStyleSheet(f"color: {prob_color}; font-size: 20px; font-weight: 900;")
        prob_vbox.addWidget(lbl_p_title, alignment=Qt.AlignmentFlag.AlignCenter)
        prob_vbox.addWidget(lbl_p_val, alignment=Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(prob_card)

        layout.addWidget(header)

        # 2. Physics & Empirical Intelligence Summary Box
        summary_box = QGroupBox("PROPAGATION & SPOTTER INTELLIGENCE ANALYSIS")
        s_layout = QVBoxLayout(summary_box)
        s_layout.setContentsMargins(12, 12, 12, 12)
        s_layout.setSpacing(6)

        prop_desc = cs.propagation.path_summary if cs.propagation else "N/A"
        dist_info = (
            f"{int(cs.propagation.distance_miles):,} mi @ {int(cs.propagation.bearing_deg)} deg"
            if cs.propagation
            else "N/A"
        )
        muf_info = format_muf_telemetry(cs.propagation)

        p = cs.propagation
        voacap_line = ""
        if p and p.predicted_snr_db is not None:
            voacap_line = (
                f"<br><b>Ray Path:</b> Mode: <span style='color:#79c0ff; font-weight:bold;'>{p.ray_mode}</span> "
                f"(Launch: {p.takeoff_angle_deg:.1f}°, Hops: {p.hop_count}) | "
                f"Path Loss: <b>{p.path_loss_db:.1f} dB</b> | "
                f"Predicted SNR: <span style='color:#3fb950; font-weight:bold;'>{p.predicted_snr_db:+.1f} dB</span> "
                f"(Reliability: {p.circuit_reliability_pct or cs.dx_percentage}%)"
            )

        lbl_phys = QLabel(
            f"<b>Ionospheric Path:</b> {prop_desc} | <b>Distance & Heading:</b> {dist_info} | "
            f"<b>Estimated MUF:</b> {muf_info}{voacap_line}"
        )
        lbl_phys.setWordWrap(True)
        s_layout.addWidget(lbl_phys)

        # Empirical Evidence details
        ev = cs.spot_evidence
        if ev:
            op_land_tag = ev.op_land_desc if (ev and ev.op_land_desc) else "Local Area"
            
            if ev.local_spotters:
                table_html = "<table style='margin-top: 8px; border-collapse: collapse; width: 100%; border: 1px solid #30363d;'>"
                table_html += "<tr style='background-color: #21262d; color: #8b949e; text-align: left;'>"
                table_html += "<th style='padding: 4px 8px; border: 1px solid #30363d;'>Callsign</th>"
                table_html += "<th style='padding: 4px 8px; border: 1px solid #30363d;'>Method</th>"
                table_html += "<th style='padding: 4px 8px; border: 1px solid #30363d;'>Dist / Age</th></tr>"
                
                for s in ev.local_spotters:
                    dist_str = f"{int(s.distance_miles)}mi" if s.distance_miles is not None else ""
                    age_str = f"{int(s.age_mins)}m ago" if getattr(s, 'age_mins', None) is not None else ""
                    dist_age_val = f"{dist_str} {age_str}".strip()
                    method_val = getattr(s, 'method', 'POTA Spot')
                    if getattr(s, 'snr', None) is not None:
                        method_val += f" ({s.snr:+.0f}dB)"
                        
                    table_html += "<tr>"
                    table_html += f"<td style='padding: 4px 8px; border: 1px solid #30363d;'><b>{s.callsign}</b></td>"
                    table_html += f"<td style='padding: 4px 8px; border: 1px solid #30363d; color: #a5d6ff;'>{method_val}</td>"
                    table_html += f"<td style='padding: 4px 8px; border: 1px solid #30363d; color: #8b949e;'>{dist_age_val}</td>"
                    table_html += "</tr>"
                table_html += "</table>"
            else:
                table_html = f"<div style='margin-top: 4px;'><i>None detected in immediate {op_land_tag} area.</i></div>"

            sig_str = ", ".join(ev.signal_reports) if ev.signal_reports else "None noted"
            state_str = ", ".join(ev.local_state_mentions) if ev.local_state_mentions else "None"

            boost_text = (
                f"<span style='color:#3fb950; font-weight:bold;'>+{ev.empirical_boost_pct} Score Boost</span>"
                if ev.empirical_boost_pct > 0
                else (
                    f"<span style='color:#f85149;'>{ev.empirical_boost_pct} Score Penalty</span>"
                    if ev.empirical_boost_pct < 0
                    else "<span style='color:#8b949e;'>Neutral (0)</span>"
                )
            )

            reason_str = f"<br><b>Reasoning:</b> <i>{ev.evidence_summary}</i>" if ev.evidence_summary else ""
            lbl_ev = QLabel(
                f"<b>Local Spotter Evidence ({op_land_tag}):</b><br>{table_html}<br>"
                f"<b>Reports & Mentions:</b> {state_str} | <b>Signal Reports:</b> {sig_str} | <b>Impact:</b> {boost_text}{reason_str}"
            )
            lbl_ev.setWordWrap(True)
            s_layout.addWidget(lbl_ev)
        else:
            s_layout.addWidget(QLabel("<i>No empirical spot stream history available for this station.</i>"))

        # View Propagation Diagram Button
        if cs.propagation:
            btn_diagram = QPushButton("View Propagation Diagram")
            btn_diagram.setStyleSheet("background-color: #238636; color: white; border-radius: 4px; padding: 6px; font-weight: bold;")
            btn_diagram.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_diagram.clicked.connect(self.show_propagation_diagram)
            s_layout.addWidget(btn_diagram)

        # Scrollable container for middle analysis insets
        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        summary_scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        summary_scroll.setWidget(summary_box)
        summary_scroll.setMaximumHeight(200)
        layout.addWidget(summary_scroll)

        # 3. Respot Stream Table (Expanded Lower Section)
        lbl_tbl = QLabel("<b>Live Respot History & Hunter Comments:</b>")
        lbl_tbl.setStyleSheet("color: #58a6ff; font-weight: bold; margin-top: 4px;")
        layout.addWidget(lbl_tbl)

        tbl = QTableWidget()
        tbl.setColumnCount(5)
        tbl.setHorizontalHeaderLabels(
            ["Spot Time", "Spotter Callsign", "Spotter Location", "Frequency / Mode", "Spot Comment"]
        )
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tbl.setColumnWidth(0, 140)
        tbl.setColumnWidth(1, 120)
        tbl.setColumnWidth(2, 160)
        tbl.setColumnWidth(3, 130)
        tbl.setColumnWidth(4, 280)

        resolver = CallsignResolver()
        respots = cs.spot.respots or []
        tbl.setRowCount(len(respots))

        for r_idx, r_item in enumerate(respots):
            s_time = r_item.get("spotTime") or ""
            s_call = str(r_item.get("spotter") or "").strip()
            s_comm = str(r_item.get("comments") or "").strip()
            s_freq = str(r_item.get("frequency") or "")
            s_mode = str(r_item.get("mode") or "")

            loc_str = "-"
            is_local = False
            if s_call:
                loc = resolver.resolve(s_call, home_lat=home_lat, home_lon=home_lon)
                is_local = loc.is_local_area
                parts = []
                if loc.state:
                    parts.append(loc.state)
                if loc.grid:
                    parts.append(loc.grid)
                if loc.distance_miles is not None:
                    parts.append(f"{int(loc.distance_miles)} mi")
                if parts:
                    loc_str = " | ".join(parts)

            item_t = QTableWidgetItem(s_time.replace("T", " ")[:19])
            is_self = is_self_spot(s_call, cs.spot.activator)
            if is_self:
                item_c = QTableWidgetItem(f"{s_call} (Self-Spot)")
                item_c.setForeground(QBrush(QColor("#8b949e")))
                item_l = QTableWidgetItem("Activator Self-Spot")
                item_l.setForeground(QBrush(QColor("#8b949e")))
            else:
                item_c = QTableWidgetItem(s_call)
                if is_local:
                    item_c.setForeground(QBrush(QColor("#58a6ff")))
                    item_c.setFont(QFont("", -1, QFont.Weight.Bold))
                item_l = QTableWidgetItem(loc_str)
                if is_local:
                    item_l.setForeground(QBrush(QColor("#7ee787")))
            item_fm = QTableWidgetItem(f"{s_freq} {s_mode}".strip() or "-")
            item_cm = QTableWidgetItem(s_comm)

            tbl.setItem(r_idx, 0, item_t)
            tbl.setItem(r_idx, 1, item_c)
            tbl.setItem(r_idx, 2, item_l)
            tbl.setItem(r_idx, 3, item_fm)
            tbl.setItem(r_idx, 4, item_cm)

        layout.addWidget(tbl, stretch=1)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

    def show_propagation_diagram(self):
        if self.cs.propagation:
            diag = PropagationDiagramWindow(self.cs.propagation, self.cs, self)
            diag.exec()

class CallsignLookupSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class CallsignLookupWorker(QRunnable):
    def __init__(self, callsign: str):
        super().__init__()
        self.callsign = callsign
        self.signals = CallsignLookupSignals()

    @pyqtSlot()
    def run(self):
        try:
            from propagation_engine import CallsignResolver
            resolver = CallsignResolver()
            loc = resolver.lookup_user_callsign(self.callsign)
            if loc:
                self.signals.finished.emit(loc)
            else:
                self.signals.finished.emit(None)
        except Exception as e:
            self.signals.error.emit(str(e))


class GeolocationSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class GeolocationWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = GeolocationSignals()

    @pyqtSlot()
    def run(self):
        try:
            import urllib.request
            import json
            from propagation_engine import latlon_to_maidenhead
            
            url = "http://ip-api.com/json/"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "POTA-Hunter-Comparator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    lat = data.get("lat")
                    lon = data.get("lon")
                    if lat is not None and lon is not None:
                        grid = latlon_to_maidenhead(lat, lon)
                        self.signals.finished.emit(grid)
                        return
            self.signals.finished.emit("")
        except Exception as e:
            self.signals.error.emit(str(e))


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(520, 420)
        self.setMinimumSize(450, 300)
        
        # Track both Home QTH Grid and P2P Park Grid in memory
        self._home_qth_grid = ""
        if parent and getattr(parent, 'home_grid', None):
            self._home_qth_grid = parent.home_grid.strip().upper()
        if not self._home_qth_grid:
            self._home_qth_grid = DEFAULT_HOME_GRID

        self._p2p_park_grid = ""
        initial_p2p_park = getattr(parent, 'p2p_my_park', '') if parent else ''
        if initial_p2p_park:
            active_spots = getattr(parent, 'active_spots', []) if parent else []
            info = fetch_park_info(initial_p2p_park, active_spots)
            if info and info.get("grid"):
                self._p2p_park_grid = info["grid"]
        
        start_p2p_val = bool(getattr(parent, 'p2p_mode', False)) if parent else False
        if start_p2p_val and parent and getattr(parent, 'current_grid', None):
            self._p2p_park_grid = parent.current_grid.strip().upper()
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.txt_call = QLineEdit(parent.my_call if parent else "")
        self.txt_call.setPlaceholderText("e.g. W8XYZ")
        form_layout.addRow("Operator Callsign:", self.txt_call)
        
        # Grid Location Input with Set Mobile/Temp button
        grid_layout = QHBoxLayout()
        current_grid_val = self._p2p_park_grid if start_p2p_val else self._home_qth_grid
        self.txt_grid = QLineEdit(current_grid_val or DEFAULT_HOME_GRID)
        self.txt_grid.setPlaceholderText("e.g. EM98dh")
        self.txt_grid.setMaxLength(6)
        
        self.btn_mobile = QPushButton("Set Mobile/Temp")
        self.btn_mobile.setToolTip("Set your current operating grid locator if away from your home QTH")
        self.btn_mobile.clicked.connect(self.set_mobile_grid)
        
        grid_layout.addWidget(self.txt_grid)
        grid_layout.addWidget(self.btn_mobile)
        form_layout.addRow("Grid Location:", grid_layout)

        # Startup Mode (At Home vs P2P Mode)
        self.chk_start_p2p = QCheckBox("Start in P2P Mode")
        self.chk_start_p2p.setChecked(start_p2p_val)
        self.chk_start_p2p.setStyleSheet("color: #bc8cff; font-weight: bold;")
        self.chk_start_p2p.setToolTip("Enable Park-to-Park (P2P) mode automatically on application startup")
        self.chk_start_p2p.toggled.connect(self.on_start_p2p_toggled)
        form_layout.addRow("Startup Mode:", self.chk_start_p2p)

        self.txt_p2p_park = QLineEdit(initial_p2p_park)
        self.txt_p2p_park.setPlaceholderText("e.g. US-1845 or K-1845")
        self.txt_p2p_park.setToolTip("Enter your P2P park reference to automatically update your Grid Location")
        self.txt_p2p_park.setEnabled(start_p2p_val)
        self.txt_p2p_park.textEdited.connect(self.on_p2p_park_text_edited)
        self.txt_p2p_park.editingFinished.connect(self.on_p2p_park_editing_finished)
        form_layout.addRow("P2P Field Park:", self.txt_p2p_park)
        
        rbn_layout = QHBoxLayout()
        self.txt_rbn = QLineEdit(getattr(parent, 'rbn_nodes_str', "W1AW") if parent else "W1AW")
        self.txt_rbn.setPlaceholderText("e.g. W1AW, K3LR, N4ZR")
        
        btn_find = QPushButton("Auto-Find Nearest")
        btn_find.clicked.connect(self.auto_find_rbn)
        
        rbn_layout.addWidget(self.txt_rbn)
        rbn_layout.addWidget(btn_find)
        form_layout.addRow("Local RBN/PSK Nodes:", rbn_layout)
        
        self.lbl_distances = QLabel("Distances: (type callsigns to calculate)")
        self.lbl_distances.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.lbl_distances.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        scroll = QScrollArea()
        scroll.setWidget(self.lbl_distances)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #30363d; border-radius: 4px; background-color: #0d1117; }")
        scroll.setMinimumHeight(80)
        
        form_layout.addRow("", scroll)

        # Map Display Mode (Auto vs Embedded Qt vs External Browser)
        self.combo_map_mode = QComboBox()
        self.combo_map_mode.addItem("Auto-Detect (Recommended)", MAP_RENDER_AUTO)
        self.combo_map_mode.addItem("Embedded Qt Window", MAP_RENDER_QT)
        self.combo_map_mode.addItem("External Web Browser (HTTP Server)", MAP_RENDER_BROWSER)
        
        current_map_mode = getattr(parent, 'map_render_mode', MAP_RENDER_AUTO) if parent else MAP_RENDER_AUTO
        mode_idx = self.combo_map_mode.findData(current_map_mode)
        if mode_idx >= 0:
            self.combo_map_mode.setCurrentIndex(mode_idx)
        form_layout.addRow("Map Display Mode:", self.combo_map_mode)
        
        self.chk_low_mem = QCheckBox("Enable Low RAM Mode (Throttles background maps)")
        self.chk_low_mem.setChecked(getattr(parent, 'low_memory_mode', False) if parent else False)
        form_layout.addRow("Performance:", self.chk_low_mem)
        
        self.txt_rbn.textChanged.connect(self._update_distances)
        self.txt_grid.textChanged.connect(self._update_distances)
        self.txt_call.editingFinished.connect(self.on_callsign_editing_finished)
        
        layout.addLayout(form_layout)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        self._update_distances()

    def on_start_p2p_toggled(self, checked: bool):
        self.txt_p2p_park.setEnabled(checked)
        if checked:
            # Instantly swap to P2P park grid if known
            if self._p2p_park_grid:
                self.txt_grid.setText(self._p2p_park_grid)
            if self.txt_p2p_park.text().strip():
                self.on_p2p_park_editing_finished()
        else:
            # Instantly swap back to Home QTH grid
            if self._home_qth_grid:
                self.txt_grid.setText(self._home_qth_grid)
            self._last_looked_up_call = None
            self.on_callsign_editing_finished()

    def on_p2p_park_text_edited(self, text: str):
        cleaned = normalize_ref(text)
        if len(cleaned) >= 4:
            active_spots = getattr(self.parent(), 'active_spots', []) if self.parent() else []
            info = fetch_park_info(cleaned, active_spots)
            if info and info.get("grid"):
                self._p2p_park_grid = info["grid"]
                if self.chk_start_p2p.isChecked():
                    self.txt_grid.setText(info["grid"])

    def on_p2p_park_editing_finished(self):
        raw_park = self.txt_p2p_park.text().strip()
        if not raw_park:
            return
        norm_ref = normalize_ref(raw_park)
        self.txt_p2p_park.setText(norm_ref)
        
        active_spots = getattr(self.parent(), 'active_spots', []) if self.parent() else []
        info = fetch_park_info(norm_ref, active_spots)
        if info and info.get("grid"):
            self._p2p_park_grid = info["grid"]
            if self.chk_start_p2p.isChecked():
                self.txt_grid.setText(info["grid"])
        else:
            worker = ParkLookupWorker(norm_ref, active_spots)
            worker.signals.finished.connect(self.on_p2p_park_lookup_finished)
            if self.parent() and hasattr(self.parent(), "threadpool"):
                self.parent().threadpool.start(worker)

    def on_p2p_park_lookup_finished(self, info: dict):
        if info and info.get("grid"):
            self._p2p_park_grid = info["grid"]
            if self.chk_start_p2p.isChecked():
                self.txt_grid.setText(info["grid"])

    def on_callsign_editing_finished(self):
        call = self.txt_call.text().strip().upper()
        if not call:
            return
            
        try:
            from propagation_engine import CallsignResolver
            res = CallsignResolver()
            loc = res.lookup_user_callsign(call)
            if loc and loc.grid:
                self._home_qth_grid = loc.grid
                if not self.chk_start_p2p.isChecked():
                    self.txt_grid.setText(loc.grid)
                return
        except Exception:
            pass
            
        if hasattr(self, "_last_looked_up_call") and self._last_looked_up_call == call:
            return
        self._last_looked_up_call = call
        
        worker = CallsignLookupWorker(call)
        worker.signals.finished.connect(self.on_callsign_lookup_finished)
        if self.parent() and hasattr(self.parent(), "threadpool"):
            self.parent().threadpool.start(worker)

    def on_callsign_lookup_finished(self, loc):
        grid_val = getattr(loc, "grid", None) if hasattr(loc, "grid") else (loc if isinstance(loc, str) else "")
        if grid_val:
            clean_g = str(grid_val).strip().upper()
            self._home_qth_grid = clean_g
            if not self.chk_start_p2p.isChecked():
                self.txt_grid.setText(clean_g)

    def set_mobile_grid(self):
        from PyQt6.QtWidgets import QInputDialog
        grid, ok = QInputDialog.getText(
            self, 
            "Set Mobile / Temporary QTH",
            "Enter your mobile grid locator (e.g. EM98dh):\n(Leave blank to auto-detect via IP Geolocation)"
        )
        if not ok:
            return
            
        grid = grid.strip().upper()
        if not grid:
            self.btn_mobile.setEnabled(False)
            self.btn_mobile.setText("Locating...")
            
            worker = GeolocationWorker()
            worker.signals.finished.connect(self.on_geolocation_finished)
            worker.signals.error.connect(self.on_geolocation_error)
            if self.parent() and hasattr(self.parent(), "threadpool"):
                self.parent().threadpool.start(worker)
        else:
            if len(grid) >= 4 and grid[:2].isalpha() and grid[2:4].isdigit():
                self.txt_grid.setText(grid)
            else:
                QMessageBox.warning(self, "Invalid Grid", "Please enter a valid 4 or 6-character Maidenhead grid locator (e.g. EM98dh).")

    def on_geolocation_finished(self, grid):
        self.btn_mobile.setEnabled(True)
        self.btn_mobile.setText("Set Mobile/Temp")
        if grid:
            self.txt_grid.setText(grid)
            QMessageBox.information(self, "Location Found", f"Successfully auto-detected your current operating grid as: {grid}")
        else:
            QMessageBox.warning(self, "Location Error", "Could not automatically determine your location. Please enter your grid manually.")

    def on_geolocation_error(self, err_msg):
        self.btn_mobile.setEnabled(True)
        self.btn_mobile.setText("Set Mobile/Temp")
        QMessageBox.warning(self, "Location Error", f"Failed to get location: {err_msg}\nPlease enter your grid manually.")
        
    def _update_distances(self):
        text = self.txt_rbn.text()
        calls = [c.strip().upper() for c in text.split(',') if c.strip()]
        if not calls:
            self.lbl_distances.setText("Distances: None")
            return
            
        home_grid = self.txt_grid.text().strip().upper()
        if not home_grid or len(home_grid) < 4:
            self.lbl_distances.setText("Distances: Needs valid home grid")
            return
            
        from data_engine import maidenhead_to_latlon
        from propagation_engine import calculate_distance_and_bearing
        from propagation_engine import CallsignResolver
        h_lat, h_lon = maidenhead_to_latlon(home_grid)
        if not h_lat:
            self.lbl_distances.setText("Distances: Invalid home grid")
            return
            
        res = CallsignResolver()
        
        html = '<table style="margin-top: 4px; border-collapse: collapse; width: 100%;" cellpadding="4">'
        html += '<tr><th align="left" style="color: #8b949e;">Node</th><th align="left" style="color: #8b949e;">Dist</th>'
        html += '<th align="left" style="color: #8b949e; padding-left: 15px;">Node</th><th align="left" style="color: #8b949e;">Dist</th></tr>'
        
        dist_data = []
        for c in calls:
            dist_str = "Unknown"
            loc = res.lookup_user_callsign(c)
            if loc and loc.grid:
                c_lat, c_lon = maidenhead_to_latlon(loc.grid)
                if c_lat and c_lon:
                    d, _ = calculate_distance_and_bearing(h_lat, h_lon, c_lat, c_lon)
                    dist_str = f"{int(d * 0.621371)} mi"
            dist_data.append((c, dist_str))
            
        for i in range(0, len(dist_data), 2):
            c1, d1 = dist_data[i]
            if i + 1 < len(dist_data):
                c2, d2 = dist_data[i+1]
                html += f'<tr><td style="color: #c9d1d9;"><b>{c1}</b></td><td style="color: #8b949e;">{d1}</td>'
                html += f'<td style="color: #c9d1d9; padding-left: 15px;"><b>{c2}</b></td><td style="color: #8b949e;">{d2}</td></tr>'
            else:
                html += f'<tr><td style="color: #c9d1d9;"><b>{c1}</b></td><td style="color: #8b949e;">{d1}</td><td colspan="2"></td></tr>'
            
        html += "</table>"
        self.lbl_distances.setText(html)
        
    def auto_find_rbn(self):
        try:
            from psk_engine import get_nearest_rbn_node, get_live_local_rbn_nodes
            from propagation_engine import maidenhead_to_latlon, CallsignResolver
        except ImportError:
            return
            
        grid = self.txt_grid.text().strip().upper()
        if not grid:
            res = CallsignResolver()
            loc = res.lookup_user_callsign(self.txt_call.text().strip().upper())
            if loc and loc.grid:
                grid = loc.grid
                
        # 1. Guaranteed fallback regional "super nodes"
        super_nodes_str = get_nearest_rbn_node(grid)
        nodes = [c.strip() for c in super_nodes_str.split(",") if c.strip()]
        
        # 2. Live scrape for exact local nodes
        live_nodes = []
        fetch_success = False
        error_msg = "No home location found."
        
        if grid:
            h_lat, h_lon = maidenhead_to_latlon(grid)
            if h_lat is not None and h_lon is not None:
                try:
                    live_nodes = get_live_local_rbn_nodes(h_lat, h_lon, max_distance_miles=200.0)
                    if live_nodes:
                        fetch_success = True
                        nodes = live_nodes + nodes
                    else:
                        error_msg = "No live skimmers found within 200 miles."
                except Exception:
                    error_msg = "Network or parsing error."
                    
        # deduplicate while preserving order
        final_nodes = []
        for n in nodes:
            if n not in final_nodes:
                final_nodes.append(n)
                
        self.txt_rbn.setText(", ".join(final_nodes))
        
        from PyQt6.QtWidgets import QMessageBox
        if fetch_success:
            QMessageBox.information(self, "Auto Detect Successful", "Successfully auto-detected regional super-nodes and live local skimmers from the Reverse Beacon Network.")
        else:
            QMessageBox.warning(self, "Live Auto Detect Incomplete", f"Failed to retrieve live local skimmers from Reverse Beacon Network ({error_msg})\n\nFell back to assigning guaranteed regional super-nodes instead.")

class DonateDialog(QDialog):
    """
    Modal dialog providing donation links to support the developer.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Support POTA Prop")
        self.resize(400, 320)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("Support the Developer")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #58a6ff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "If you find POTA Prop useful and would like to help support its continued "
            "development, consider buying me a coffee! Your support is greatly appreciated."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #e6edf3; font-size: 13px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        # PayPal Button
        paypal_btn = QPushButton("Donate via PayPal ($5)")
        paypal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        paypal_btn.setStyleSheet("""
            QPushButton {
                background-color: #0070ba;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #005ea6;
            }
        """)
        paypal_btn.clicked.connect(lambda: webbrowser.open("https://paypal.me/w7kmc/5"))
        layout.addWidget(paypal_btn)

        # Ko-fi Button
        kofi_btn = QPushButton("Donate via Ko-fi")
        kofi_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        kofi_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5e5b;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e05350;
            }
        """)
        kofi_btn.clicked.connect(lambda: webbrowser.open("https://ko-fi.com/w7kmc"))
        layout.addWidget(kofi_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class AboutDialog(QDialog):
    """
    Modal dialog displaying software version, application overview, key features,
    safety disclaimers, and helpful web links for POTA Prop.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About POTA Prop")
        self.resize(650, 720)
        self.setMinimumSize(600, 580)
        self.setStyleSheet(DARK_STYLESHEET)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Scrollable content container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #30363d;
                border-radius: 8px;
                background-color: #0d1117;
            }
        """)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # App Header
        app_name = QLabel("POTA Prop")
        app_name.setStyleSheet("font-size: 24px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(app_name)

        version_label = QLabel(f"Software Version: {APP_VERSION}")
        version_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #7ee787;")
        layout.addWidget(version_label)

        # Author / Design Attribution
        author_label = QLabel("Designed and tested by <b>Kevin McGrath - W7KMC</b>")
        author_label.setWordWrap(True)
        author_label.setStyleSheet("color: #e6edf3; font-size: 13px; padding: 2px 0px;")
        layout.addWidget(author_label)

        # Description
        desc_label = QLabel(
            "POTA Prop compares your historical hunted parks log against live active spots "
            "from pota.app in real-time. It provides propagation estimations, multi-layer ionospheric "
            "modeling (1E–4F2), skip-zone cutoff calculations, Open-Meteo local weather forecasts, "
            "and regional 750-mile Blitzortung.org lightning QRN monitoring."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #8b949e; line-height: 1.4; font-size: 12px;")
        layout.addWidget(desc_label)

        # Feature Summary List
        features_box = QGroupBox("Key Features")
        features_layout = QVBoxLayout(features_box)
        features_layout.setContentsMargins(12, 12, 12, 12)
        features_layout.setSpacing(4)

        features = [
            "• Live POTA spot & respot stream synchronization with evidence parsing",
            "• UN ISO 3166-1/2 POTA country database integration with clean location formatting & DXCC context",
            "• Interactive Live Propagation & Weather Map with 100W link budget heatmap, RainViewer & NOAA Doppler radar, Blitzortung lightning cluster vectors & NOAA SWPC Aurora Ovals (F4 / F11)",
            "• Full mode support & decoding thresholds (CW, SSB, FT8, FT4, JS8, PSK, FM, AM, Other Digital)",
            "• Live RBN & PSKReporter intelligence for empirical skip-zone and SNR verification",
            "• Multi-layer ionospheric modeling (E, F1, F2), NOAA SWPC D-RAP absorption & multi-hop ray tracing",
            "• Skip-zone cutoff calculations based on operating frequency and distance",
            "• 750-mile Blitzortung.org lightning stream & ITU-R P.372 QRN noise calculations",
            "• Storm cell trajectory tracking, ground motion vectors, & Time of Arrival (TOA) estimates",
            "• Open-Meteo local weather integration with 12-hour hourly forecast & 24-hour UTC times",
            "• Station link budget calculations with transmitter power (Watts) & antenna patterns",
            "• Preferences & Startup Mode manager (Home QTH vs. P2P Mode with auto park grid updates)",
            "• Auto-comparison with local hunted CSV log, P2P portable mode & worked status tracking",
        ]

        for f in features:
            lbl = QLabel(f)
            lbl.setStyleSheet("color: #8b949e; font-size: 12px; border: none; background: transparent;")
            features_layout.addWidget(lbl)

        layout.addWidget(features_box)
        
        # Credits & Data Sources
        credits_box = QGroupBox("Data Sources & Credits")
        credits_layout = QVBoxLayout(credits_box)
        credits_layout.setContentsMargins(12, 10, 12, 10)
        
        credits_text = (
            "POTA Prop heavily relies on the incredible work of the following open platforms and data sources. "
            "Please consider supporting them or contributing to their crowdsourced networks:<br/><br/>"
            "• <b>Parks on the Air (POTA)</b> - The core spot stream and official park database. (<a href='https://parksontheair.com' style='color:#58a6ff;'>parksontheair.com</a>)<br/>"
            "• <b>Blitzortung.org</b> - Real-time crowd-sourced lightning telemetry. (<a href='https://www.blitzortung.org' style='color:#58a6ff;'>blitzortung.org</a>)<br/>"
            "• <b>RainViewer</b> - Live Doppler weather radar API. (<a href='https://www.rainviewer.com' style='color:#58a6ff;'>rainviewer.com</a>)<br/>"
            "• <b>IEM / NOAA Nexrad</b> - Live US weather radar tiles. (<a href='https://mesonet.agron.iastate.edu/' style='color:#58a6ff;'>mesonet.agron.iastate.edu</a>)<br/>"
            "• <b>PSKReporter & RBN</b> - Live reverse beacon network spotting. (<a href='https://pskreporter.info' style='color:#58a6ff;'>pskreporter.info</a>)<br/>"
            "• <b>Open-Meteo</b> - Excellent free, open-source weather API. (<a href='https://open-meteo.com' style='color:#58a6ff;'>open-meteo.com</a>)<br/>"
            "• <b>NOAA SWPC</b> - Space weather data (SFI, K-index), D-RAP Absorption & OVATION Aurora Oval models. (<a href='https://www.swpc.noaa.gov' style='color:#58a6ff;'>swpc.noaa.gov</a>)<br/>"
            "• <b>Carto & OpenStreetMap</b> - Map rendering and basemap tiles. (<a href='https://www.openstreetmap.org' style='color:#58a6ff;'>openstreetmap.org</a>)"
        )
        credits_lbl = QLabel(credits_text)
        credits_lbl.setOpenExternalLinks(True)
        credits_lbl.setWordWrap(True)
        credits_lbl.setStyleSheet("color: #8b949e; font-size: 11px; line-height: 1.4; border: none; background: transparent;")
        credits_layout.addWidget(credits_lbl)
        layout.addWidget(credits_box)
        
        # License Box
        license_box = QGroupBox("License")
        license_layout = QVBoxLayout(license_box)
        license_layout.setContentsMargins(12, 10, 12, 10)
        
        license_lbl = QLabel(
            "This project is licensed under the <b>GNU General Public License v3.0 (GPLv3)</b>. "
            "You are free to use, modify, and distribute this software for amateur radio purposes, "
            "provided that any derivative works are also open-source and released under the same GPLv3 license."
        )
        license_lbl.setWordWrap(True)
        license_lbl.setStyleSheet("color: #8b949e; font-size: 11px; line-height: 1.4; border: none; background: transparent;")
        license_layout.addWidget(license_lbl)
        layout.addWidget(license_box)

        # Safety Disclaimer & Limitation of Liability Box
        disclaimer_box = QGroupBox("Safety Disclaimer & Limitation of Liability")
        disclaimer_layout = QVBoxLayout(disclaimer_box)
        disclaimer_layout.setContentsMargins(12, 10, 12, 10)

        disclaimer_lbl = QLabel(
            "<b>FOR RECREATIONAL & INFORMATIONAL USE ONLY:</b> POTA Prop is provided solely for "
            "amateur radio recreation and educational modeling. Weather forecasts, lightning motion tracking, "
            "Time of Arrival (TOA) estimates, convective alerts, and propagation models must <b>NOT</b> be relied upon "
            "for life safety, weather hazard prediction, or field emergency planning. Severe weather, lightning strikes, "
            "and atmospheric conditions can change, intensify, or strike rapidly without warning or remote detection. "
            "Operators remain solely responsible for field safety. The developer and contributors disclaim any and all liability "
            "for personal injury, property damage, equipment loss, or inaccuracies arising out of or in connection with the use of "
            "or reliance upon this software."
        )
        disclaimer_lbl.setWordWrap(True)
        disclaimer_lbl.setStyleSheet("color: #ffa657; font-size: 11px; line-height: 1.4; border: none; background: transparent;")
        disclaimer_layout.addWidget(disclaimer_lbl)
        layout.addWidget(disclaimer_box)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

        # Footer Buttons
        btn_layout = QHBoxLayout()

        web_btn = QPushButton("Visit POTA.app")
        web_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        web_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #58a6ff;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #58a6ff;
            }
        """)
        web_btn.clicked.connect(lambda: webbrowser.open("https://pota.app"))
        btn_layout.addWidget(web_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        main_layout.addLayout(btn_layout)



class DocumentationDialog(QDialog):
    """
    Comprehensive User Guide and Documentation modal dialog for POTA Prop.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("POTA Prop - User Guide & Reference")
        self.resize(880, 680)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Header Frame
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #1c2128;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px 14px;
            }
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)

        lbl_title = QLabel("POTA Prop User Guide & Reference")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        h_layout.addWidget(lbl_title)
        h_layout.addStretch()

        layout.addWidget(header)

        # Documentation Scroll Area with Rich Text
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #30363d;
                border-radius: 8px;
                background-color: #0d1117;
            }
        """)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(20, 18, 20, 18)
        c_layout.setSpacing(18)

        docs_text = QLabel()
        docs_text.setWordWrap(True)
        docs_text.setOpenExternalLinks(True)
        docs_text.setTextFormat(Qt.TextFormat.RichText)
        docs_text.setStyleSheet("color: #e6edf3; font-size: 13px; line-height: 1.5;")

        docs_html = f"""
        <h1 style="color: #7ee787; font-size: 18px; margin-top: 0; border-bottom: 2px solid #238636; padding-bottom: 6px;">PART I: APPLICATION OPERATION & SETUP</h1>

        <h2 style="color: #58a6ff; margin-top: 14px;">1. Getting Started: Preferences & Hunter Log Setup</h2>
        <p><b>POTA Prop</b> is a desktop application designed for amateur radio operators hunting Parks on the Air. It compares live activator spots from <a href="https://pota.app" style="color: #7ee787;">pota.app</a> against your historical hunted CSV log, estimating contact probability using ionospheric ray tracing, live space weather, and regional atmospheric lightning noise (QRN).</p>
        
        <h3 style="color: #7ee787;">Step-by-Step Initial Setup & Preferences (Ctrl+P):</h3>
        <ol>
            <li><b>Authenticate with POTA.app:</b> Click the <b>Sign In POTA.app</b> button on the top toolbar. A secure browser window will open, allowing you to log into your pota.app account. Once signed in, POTA Prop will automatically extract your authentication token and close the window.</li>
            <li><b>Auto-Sync Your Hunter Log:</b> Once authenticated, click <b>Sync Log</b> (or <b>Sync POTA Data</b>). The application will instantly connect to the POTA API, download your entire historical hunted log, and integrate it into the application automatically.</li>
            <li><b>Preferences Manager (Ctrl+P):</b> Open <i>File &rarr; Preferences</i> (or press <b>Ctrl+P</b>) to configure:
                <ul>
                    <li><b>Operator Callsign:</b> Enter your callsign (e.g. <code>W8XYZ</code>). The app automatically queries online databases to identify your Maidenhead grid locator.</li>
                    <li><b>Grid Location:</b> Displays your active operating grid square. Click <b>Set Mobile/Temp</b> to auto-detect your location via IP Geolocation when away from home.</li>
                    <li><b>Startup Mode (Home vs. P2P):</b> Choose whether the application starts at your Home QTH or in <b>P2P Mode</b>. Checking <b>Start in P2P Mode</b> enables the <b>P2P Field Park</b> input, which automatically queries the park and updates your Grid Location on startup.</li>
                    <li><b>Local RBN/PSK Nodes:</b> Click <b>Auto-Find Nearest</b> to automatically identify the nearest active reverse beacon skimmers within 200 miles.</li>
                </ul>
            </li>
        </ol>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">2. Multi-Criteria Filtering, Instant Search & Station Setup</h2>
        <ul>
            <li><b>Multi-Criteria Filters:</b> Filter spots by Status (<i>All</i>, <i>New</i>, <i>Hunted</i>, <i>Worked</i>, <i>P2P</i>), Score Threshold (<i>All</i>, <i>&ge;25</i>, <i>&ge;50</i>, <i>&ge;75</i>, <i>&ge;99</i>), Band, and Mode (<i>CW</i>, <i>SSB</i>, <i>FT8</i>, <i>FT4</i>, <i>JS8</i>, <i>PSK</i>, <i>FM</i>, <i>AM</i>, <i>Other Digital</i>).</li>
            <li><b>Instant Search:</b> Type any callsign, park reference, park name, state, grid, or comment keyword into the search box for real-time table filtering.</li>
            <li><b>Transmitter Power (Watts):</b> Select your rig's output power (QRP 5W, 10W, 20W, 50W, 100W, 500W, or 1500W Legal Limit). The link budget calculation adjusts transmitter output in dBW and expected receiver SNR accordingly.</li>
            <li><b>Dynamic Antenna Elevation Modeling:</b> Choose your antenna setup (Dipole, End-Fed Half Wave, Vertical, Magnetic Loop, Random Wire, 3-Element Beam, VHF Collinear, or Rubber Duck / HT). POTA Prop calculates the take-off launch angle (&Delta;) from the ray-tracer and computes the antenna's gain G(&Delta;, f) at that elevation angle:
                <ul>
                    <li><b>Beam / Yagi / Hexbeam:</b> Provides low-angle DX gain (&Delta; 5°–20°) for long-distance multi-hop paths.</li>
                    <li><b>Vertical (1/4-wave / 5/8-wave):</b> Low takeoff lobe (+4.5 to +5.5 dBi at &Delta; 8°–22°), with reduced response at steep NVIS angles (&Delta; &gt; 45°).</li>
                    <li><b>Dipole (1/2-wave @ 0.5&lambda;):</b> Broad elevation pattern at high NVIS angles (&Delta; 40°–65°), with standard response at DX angles.</li>
                    <li><b>End-Fed Half Wave (EFHW):</b> Multi-band half-wave performance with realistic unun transformer loss.</li>
                    <li><b>Magnetic Loop:</b> Compact QRP loop pattern with ground efficiency adjustments.</li>
                    <li><b>Random Wire / Compromised:</b> Emulates field wire antennas with unun transformer and counterpoise ground loss factors.</li>
                    <li><b>Rubber Duck / HT:</b> Handheld whip calibrated with severe shortening losses on HF while maintaining authentic VHF/UHF line-of-sight performance.</li>
                </ul>
            </li>
            <li><b>Park-to-Park (P2P) Mode:</b> Operating portable from a park? Check the <b>P2P Mode</b> checkbox on the toolbar and enter your field park reference (e.g. <code>US-1845</code>). The app resolves your park's grid and re-centers all distance, bearing, and propagation calculations from your active park grid.</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">3. Interactive Live Propagation, Space Weather & Doppler Radar Map</h2>
        <p>The <b>Live Map</b> provides a real-time, hardware-accelerated global visualization of your station's link budget, active activator pins, Doppler weather radar, space weather boundaries, and regional thunderstorm clusters. Click the green <b>Live Map</b> button on the top toolbar, press <b>F4</b>, or select <i>View &rarr; Live Propagation & Weather Map (F4)</i> to launch.</p>
        
        <h3 style="color: #7ee787;">1. Floating Propagation Controls HUD:</h3>
        <p>The floating HUD panel in the top-right corner allows dynamic control over all map layers and filters without obscuring the globe:</p>
        <ul>
            <li><b>Collapsible Panel:</b> Click the <b>▼</b> button to collapse the HUD into a compact title bar, freeing up screen real estate for wide-angle map viewing. Click <b>▶</b> to expand it.</li>
            <li><b>Independent Band & Mode Selectors:</b> Select any amateur band (160m through 70cm) and operating mode (CW, SSB, FT8, FT4, JS8, PSK, FM, AM, Other Digital). The dropdown dynamically displays <b>live active park counts</b> for each band (e.g. <code>20m (45)</code>, <code>40m (28)</code>, <code>All Spots (135 Parks)</code>). Changing the band or mode immediately recalculates the 100W propagation heatmap and filters the active spot pins.</li>
            <li><b>Heatmap Opacity Slider:</b> Dedicated slider (0.0 to 1.0) on an isolated rendering pane (<code>heatmapPane</code>) allowing you to adjust the transparency of the RF coverage heatmap without dimming basemap vector features, Grayline terminator lines, or storm markers.</li>
            <li><b>Dark Map Mode Basemap Toggle:</b> Seamlessly switch between clean high-contrast Carto Light and sleek Carto Dark basemaps.</li>
            <li><b>Native Fullscreen Mode (F11 / Esc / ⛶):</b> Click the <b>⛶</b> button or press <b>F11</b> to enter immersive, borderless fullscreen mode (ideal for dedicated auxiliary station monitors or wall displays). Press <b>Esc</b> or <b>F11</b> to exit.</li>
            <li><b>Live Update Telemetry Indicator:</b> Displays the real-time UTC timestamp of the latest propagation recalculation (e.g. <code>Last Updated: 14:30 UTC</code>) or <code>Updating... Standby...</code> during background calculation passes.</li>
        </ul>

        <h3 style="color: #7ee787;">2. Real-Time 100W Propagation Heatmap & Physics Modeling:</h3>
        <p>POTA Prop continuously computes your station's RF link budget across the entire globe using 1° latitude by 2° longitude Maidenhead sub-square resolution:</p>
        <ul>
            <li><b>Physics-Based Multi-Stage Color Scale:</b>
                <ul>
                    <li><b style="color: #2ea043;">Green (≥99% / 100%):</b> Exceptional Propagation — path is wide open with robust SNR well above mode decoding thresholds.</li>
                    <li><b style="color: #d29922;">Yellow / Gold (50%–99%):</b> Good / High Probability — reliable skywave path within favorable MUF window.</li>
                    <li><b style="color: #f78166;">Orange (25%–50%):</b> Marginal / Elevated Path Loss — weak signals near the receiver noise floor; higher power or directional antennas recommended.</li>
                    <li><b style="color: #da3633;">Red (&lt;25%):</b> Poor / Closed — path suffers from skip-zone ionospheric penetration, heavy daytime D-layer absorption, or severe attenuation.</li>
                </ul>
            </li>
            <li><b>Interactive Grid Hover Score:</b> Move your mouse cursor anywhere across oceans or continents to read the precise predicted percentage (<code>Propagation Score: XX%</code>) in the HUD footer.</li>
            <li><b>Lifecycle & Background Recalculation:</b> The heatmap recalculates upon initial map open, instantly whenever you change the band or mode in the HUD, and automatically on a strict <b>10-minute cadence</b> via a non-blocking background worker thread (<code>MapPropagationWorker</code>). Spot pin updates (every 15s) update cleanly without interrupting map interaction.</li>
        </ul>

        <h3 style="color: #7ee787;">3. Active POTA Spot Pins & Click Diagnostics:</h3>
        <p>Every active activator on the air is plotted at their park's exact geographic coordinates with interactive vector pins:</p>
        <ul>
            <li><b>Two-Dimensional Pin Styling (Score Fill + Hunted Ring):</b>
                <ul>
                    <li><b>Interior Fill Color (QSO Score):</b> Circular markers are filled according to predicted QSO score: <span style="color: #2ea043; font-weight: bold;">Green (≥99)</span>, <span style="color: #d29922; font-weight: bold;">Yellow (≥75)</span>, <span style="color: #f78166; font-weight: bold;">Orange (≥50)</span>, and <span style="color: #da3633; font-weight: bold;">Red (&lt;50)</span>.</li>
                    <li><b style="color: #ffffff;">⚪ Crisp White Border Ring:</b> Marks <b>NEW (Unhunted)</b> parks, immediately drawing your eye to clean references.</li>
                    <li><b style="color: #f85149;">🔴 Crimson Red Border Ring:</b> Marks <b>WORKED (Already Hunted)</b> parks already logged in your POTA history.</li>
                </ul>
            </li>
            <li><b>Local Verification <code>+</code> Badge:</b> Markers feature a bold white <b><code>+</code></b> symbol if independent third-party spotters in your regional call area or DXCC entity have recently confirmed receiving the activator's signal.</li>
            <li><b>Activator QRP Power Modeling (⚡):</b>
                <ul>
                    <li>The engine automatically performs case-insensitive parsing of QRP announcements (e.g. <code>5W</code>, <code>10W</code>, <code>QRP</code>, <code>KX2</code>, <code>KX3</code>, <code>IC-705</code>, <code>TX-500</code>, <code>/QRP</code>) from activator respots and comments.</li>
                    <li>Transmitter power is dynamically reduced from the 100W baseline (&Delta;P = &minus;13 dB for 5W, &minus;10 dB for 10W), adjusting received SNR directly against your station's real-time ITU-R P.372 atmospheric noise floor and summer lightning QRN surges.</li>
                    <li>Displays gold <span style="color: #e3b341; font-weight: bold;">[⚡ QRP 5W]</span> badges in map popups, table rows, and telemetry tooltips.</li>
                </ul>
            </li>
            <li><b>HUD Legend Status Key:</b> The floating HUD features mini preview dots (<span style="color: #c9d1d9;">⚪ New &nbsp;|&nbsp; 🔴 Worked &nbsp;|&nbsp; + Local</span>) for quick reference.</li>
            <li><b>Interactive Click Popups:</b> Click any spot marker to reveal a detailed diagnostic popup showing:
                <ul>
                    <li><b>Activator Callsign, Status & QRP:</b> Callsign (e.g. <code>W1AW/P</code>), <span style="color: #58a6ff; font-weight: bold;">[NEW]</span> or <span style="color: #f85149; font-weight: bold;">[WORKED]</span> status badge, and <span style="color: #e3b341; font-weight: bold;">[⚡ QRP]</span> power tag.</li>
                    <li><b>Park Reference & Name:</b> Official POTA reference code and park description.</li>
                    <li><b>Frequency & Mode:</b> Active operating frequency (MHz) and mode.</li>
                    <li><b>QSO Score:</b> Estimated success probability with <code>+</code> verification badge (e.g. <code>Score: 92+</code>).</li>
                    <li><b>Path MUF & Color Dot:</b> Estimated Maximum Usable Frequency in MHz with a quick-reference color indicator dot (<span style="color: #2ea043;">● Green &ge; 28 MHz</span>: upper HF open; <span style="color: #d29922;">● Yellow 18–28 MHz</span>: mid-HF open; <span style="color: #da3633;">● Red &lt; 18 MHz</span>: upper HF closed).</li>
                </ul>
            </li>
        </ul>

        <h3 style="color: #7ee787;">4. Dual-Source Live Doppler Weather Radar:</h3>
        <p>Monitor real-time weather systems and approaching precipitation over your QTH or target parks using two selectable radar engines:</p>
        <ul>
            <li><b>RainViewer Global Radar:</b> Seamless worldwide precipitation reflectivity composite layer automatically updated every 10 minutes via the RainViewer Open API. Includes an independent opacity slider (0.0 to 1.0).</li>
            <li><b>US NOAA / IEM NEXRAD Composite:</b> High-resolution base reflectivity (N0Q) composite radar tiles covering the continental United States from Iowa Environmental Mesonet / NOAA, with an independent opacity slider.</li>
        </ul>

        <h3 style="color: #7ee787;">5. Day/Night Solar Terminator (Grayline):</h3>
        <p>Toggle <b>Show Grayline</b> to display real-time astronomical and twilight boundaries with seamless global longitudinal wrapping (-720° to +720°):</p>
        <ul>
            <li><b>Solid Black Line:</b> Exact 90° solar zenith angle (sunrise/sunset terminator line).</li>
            <li><b>Dashed Black Line:</b> 96° solar zenith angle (civil twilight boundary).</li>
            <li><b>Dashed Gray Line:</b> 84° solar zenith angle (golden hour daylight boundary).</li>
        </ul>

        <h3 style="color: #7ee787;">6. NOAA SWPC Space Weather Aurora Oval (OVATION Model):</h3>
        <p>Toggle <b>Show Aurora Oval</b> to render real-time Northern (Aurora Borealis) and Southern (Aurora Australis) auroral boundaries fetched from NOAA SWPC on a 15-minute background cycle:</p>
        <ul>
            <li><b>Core Auroral Belts:</b> Rendered in bold dark green polylines indicating primary ionospheric auroral electrojet activity.</li>
            <li><b>Equatorward Viewlines:</b> Rendered in dark gray dashed polylines showing the southernmost (northern hemisphere) and northernmost (southern hemisphere) boundaries where aurora is visible on the horizon.</li>
        </ul>

        <h3 style="color: #7ee787;">7. Blitzortung.org Live Lightning Clusters & Storm Velocity Vectors:</h3>
        <p>Toggle <b>Show Lightning Clusters</b> to view real-time convective thunderstorm cells and severe weather tracking within your 750-mile operating radius:</p>
        <ul>
            <li><b>Stationary Storms (<code>⚡</code>):</b> Rendered as a glowing yellow bolt inside a semi-transparent circular boundary for localized or stationary storms.</li>
            <li><b>Moving Storm Cells (<code>⚡➤</code>):</b> Rendered with an animated directional arrow rotated along the storm cell's exact ground motion heading vector.</li>
            <li><b>Lightning Cluster Popups:</b> Click any lightning marker to inspect event category (Severe Thunderstorm, Tornado Warning, Marine Warning, Flash Flood), estimated stroke count, storm ground speed (mph), cardinal heading degrees, and active NOAA NWS convective alert warning headlines.</li>
        </ul>

        <h3 style="color: #7ee787;">8. Hybrid Desktop & Chromebook Architecture:</h3>
        <p>POTA Prop delivers optimal performance across all computing environments:</p>
        <ul>
            <li><b>Standard Desktops (Linux / Windows):</b> Uses embedded Qt6 <code>QWebEngineView</code> with a high-speed bidirectional <code>QWebChannel</code> bridge.</li>
            <li><b>Chromebooks (ChromeOS Crostini) & Browser Fallback:</b> Automatically starts a secure, multi-threaded local HTTP server (<code>map_server.py</code>) on a random port with tokenized authentication, seamlessly launching in ChromeOS Chrome with full GPU hardware acceleration.</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">4. Marking Contacts Off Your List & Community Spotting</h2>
        <h3 style="color: #7ee787;">How to Mark a Contact as Worked:</h3>
        <p>When you complete a QSO with an active park, you can update your session tracking:</p>
        <ul>
            <li><b>Status Cell Dropdown:</b> Click the drop-down menu in the <b>Status</b> column of the activator's row and select <b>Mark [WORKED]</b>. The row immediately turns green, and your metric counters update in real-time.</li>
            <li><b>Right-Click Menu:</b> Right-click anywhere on the row and select <b>Mark Park as [WORKED]</b>.</li>
            <li><b>Action Bar:</b> Select any row and click the <b>Mark [WORKED]</b> button at the bottom right.</li>
        </ul>

        <h3 style="color: #7ee787;">00:00 UTC New Day Rollover & <code>Hunted(W)</code> Badge:</h3>
        <p>Under official POTA rules, a new UTC day (00:00Z) resets the park QSO eligibility window, allowing you to hunt and log that park again for daily awards. When 00:00 UTC rolls over while a park is still active:</p>
        <ul>
            <li>Parks worked on the previous UTC day automatically transition to <b><code>Hunted(W)</code></b> (or <b><code>[P2P] Hunted(W)</code></b> in Park-to-Park mode).</li>
            <li>The <b>(W)</b> denotes that the park was worked during the previous UTC day and is now eligible to be hunted again today.</li>
            <li>Once you work the park on the new UTC day, selecting <b>Mark [WORKED] Today</b> updates its badge back to <b><code>[WORKED]</code></b>.</li>
        </ul>

        <h3 style="color: #7ee787;">Automatic Re-Spotting Prompt:</h3>
        <p>When you mark a park as worked, POTA Prop displays a prompt asking if you'd like to open <code>pota.app</code> to re-spot the activator. Clicking <b>Open pota.app to Spot</b> takes you straight to the park page in your browser so you can submit your spot.</p>

        <h3 style="color: #7ee787;">Community Re-Spotting:</h3>
        <p>Re-spotting updates the global POTA network, refreshing the activator's active window and providing current spot evidence for other hunters in your region.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">5. Custom Filter Presets & Quick Shortcuts</h2>
        <p>Create tailored operating views to match your equipment and preferences:</p>
        <ul>
            <li><b>Creating Presets:</b> Adjust your filters (e.g. <i>New Only</i> + <i>20m</i> + <i>CW</i> + <i>Score &ge; 50</i>). Click <b>Filter Presets</b> &rarr; <b>Save Current as Preset...</b> and give it a name (e.g., <i>"20m CW Hunt"</i>).</li>
            <li><b>Loading Presets:</b> Select your saved preset from the <b>Filter Presets</b> menu to restore your complete filtering state instantly.</li>
        </ul>
        
        <h3 style="color: #7ee787;">Keyboard Shortcuts:</h3>
        <table border="0" cellpadding="5" cellspacing="0" style="color: #c9d1d9; font-size: 13px;">
            <tr><td><b style="color: #58a6ff;">F1</b></td><td>Open About POTA Prop window</td></tr>
            <tr><td><b style="color: #58a6ff;">F2 / Ctrl+H</b></td><td>Open this Documentation & Guide window</td></tr>
            <tr><td><b style="color: #58a6ff;">F4</b></td><td>Open Live Propagation, Space Weather & Doppler Radar Map</td></tr>
            <tr><td><b style="color: #58a6ff;">F5</b></td><td>Trigger immediate manual spot & weather refresh</td></tr>
            <tr><td><b style="color: #58a6ff;">F6</b></td><td>Open Receiver Band Noise Floor Matrix dialog</td></tr>
            <tr><td><b style="color: #58a6ff;">F11</b></td><td>Toggle Fullscreen Mode (in Live Map window)</td></tr>
            <tr><td><b style="color: #58a6ff;">Esc</b></td><td>Exit Fullscreen Mode (in Live Map window)</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+P</b></td><td>Open Preferences Manager</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+O</b></td><td>Reload / Browse Hunter Log CSV</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+S</b></td><td>Export current table view to CSV</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+Q</b></td><td>Exit Application</td></tr>
        </table>

        <br />
        <h1 style="color: #7ee787; font-size: 18px; margin-top: 16px; border-bottom: 2px solid #238636; padding-bottom: 6px;">PART II: PROPAGATION MODELING & TELEMETRY GUIDE</h1>

        <h2 style="color: #58a6ff; margin-top: 14px;">6. QSO Score, Reliability (REL), and The "+" Local Verification Symbol</h2>
        <p>POTA Prop calculates an estimated <b>QSO Score</b> (0 to 100+) for every active spot. This score estimates the likelihood of completing a QSO with that activator based on ray-hop geometry, link budget SNR, ionospheric absorption, regional lightning QRN noise, and real-time spotter reports.</p>
        
        <h3 style="color: #7ee787;">What Does the "+" Symbol Mean (e.g. <code>85+</code>)?</h3>
        <p>The <b><code>+</code> symbol</b> next to a score indicates <b>Local Spot Verification</b>. When independent third-party spotters in your geographical region (e.g., nearby call areas, local spotters, or fellow hams in your country if you are DX) re-spot an activator, it indicates that the signal is actively propagating into your area. The engine adds a score adjustment and marks the spotter comment with a green <code>+</code> tag.</p>
        <p><b>Global DXCC Support:</b> Whether you are in US 8-Land, Canada, France, or Australia, POTA Prop uses a global RegionalPathMatrix that automatically understands your home DXCC entity and maps spotter regions worldwide to provide tailored verification bonuses to your location!</p>
        <p><b>Activator Self-Spot Protection:</b> Activator self-spots (where the spotter callsign matches the activator) are not counted as third-party local spotters, preventing self-spots from triggering a <code>+</code> badge. Self-spot comments are still parsed for frequency changes and QRT notifications.</p>

        <h3 style="color: #7ee787;">Diagnostic Mouseover Tooltips:</h3>
        <p>Hover your mouse cursor over any <b>Score</b> badge or table row to view a detailed popup containing path diagnostics: ray mode (e.g., <i>1F2</i>, <i>2F2</i>), launch takeoff angle, dynamic antenna gain at that takeoff angle, estimated path loss in dB, predicted receiver SNR in dB, estimated Maximum Usable Frequency (MUF), Grayline status, and regional lightning QRN surges.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">7. Multi-Layer Ionospheric Profiling & Multi-Hop Ray Tracing</h2>
        <p>POTA Prop models how radio waves refract through the ionosphere using standard ionospheric layers and ray geometry:</p>
        
        <h3 style="color: #7ee787;">1. Multi-Layer Ionospheric Profile (E, F1, F2 Layers):</h3>
        <ul>
            <li><b>E-Layer (foE, hmE = 110 km):</b> Modeled using solar-zenith Chapman theory: <code>foE = 0.9 × [(180 + 1.44 × SFI) × cos(χ)]^0.25</code>. Governs daytime absorption and short-hop E-layer reflections.</li>
            <li><b>F1-Layer (foF1, hmF1 = 200 km):</b> Intermediate daytime layer (<code>foF1 ≈ 1.4 × foE</code>) causing wave refraction during summer daylight.</li>
            <li><b>F2-Layer (foF2, hmF2, ymF2):</b> The primary reflector for long-distance HF communication. Peak height <code>hmF2</code> ranges from 220 km to 420 km depending on solar flux and diurnal variation. Semi-thickness <code>ymF2</code> is modeled parabolically.</li>
            <li><b>Geomagnetic Storm Depletion:</b> During geomagnetic storms (high K-index and A-index), sub-storm negative phases deplete F2-layer electron density, lowering foF2 and reducing the path MUF.</li>
        </ul>

        <h3 style="color: #7ee787;">2. Candidate Multi-Hop Ray Modes (1E, 2E, 1F2, 2F2, 3F2, 4F2):</h3>
        <p>The engine tests multiple ray mode candidates across the Great-Circle path to find the dominant, lowest-loss path:</p>
        <ul>
            <li><b>Take-Off Launch Elevation Angle (&Delta;):</b> Solved using spherical trigonometry:
                <br /><code>tan(&Delta;) = [cos(d_hop / 2R) - R / (R + h')] / sin(d_hop / 2R)</code>
                <br />Paths requiring launch angles below 1.5° receive penalties due to terrain and ground clutter.</li>
            <li><b>Ionospheric Incidence Angle (&phi;<sub>inc</sub>):</b> Computed at the ionospheric reflection height:
                <br /><code>sin(&phi;<sub>inc</sub>) = [R / (R + h')] × cos(&Delta;)</code></li>
            <li><b>Oblique Secant Law:</b> Determines the Maximum Usable Frequency for that hop geometry:
                <br /><code>f_oblique = fo / cos(&phi;<sub>inc</sub>) = fo × sec(&phi;<sub>inc</sub>)</code></li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">8. Skip-Zone & Oblique Critical Frequency Calculations</h2>
        <p>Ionospheric propagation depends on whether operating frequencies exceed the oblique critical frequency for a given path distance:</p>

        <h3 style="color: #7ee787;">How Skip-Zone Conditions Occur:</h3>
        <ul>
            <li><b>Oblique Reflection Condition:</b> For a radio wave to refract back to Earth, the operating frequency must be less than or equal to the oblique critical frequency: <code>f &le; foF2 × sec(&phi;<sub>inc</sub>)</code>.</li>
            <li><b>Ionospheric Penetration (Skip Zone):</b> On short-distance paths (e.g. 200–500 miles), the radio wave strikes the F2 layer at a steep angle (&phi;<sub>inc</sub> is small, sec(&phi;<sub>inc</sub>) &approx; 1.1–1.3). If foF2 is low, high frequencies penetrate through the ionosphere rather than reflecting.</li>
            <li><b>Nighttime foF2 Decay:</b> At night, reduced solar radiation causes foF2 to drop to 3–5 MHz, leading higher HF bands to penetrate.</li>
            <li><b>Engine Action:</b> When penetration occurs, the engine sets the status to <code>Closed (Skip Zone / Penetration: Freq > Oblique MUF)</code> and adjusts the probability score accordingly.</li>
        </ul>
        
        <h3 style="color: #7ee787;">Global Propagation Skip Diagrams:</h3>
        <p>The interactive map visually graphs these mechanics. Paths that are open via groundwave or forced open by empirical network telemetry are drawn as <b>solid green lines</b>. Paths that suffer from mathematical skip-zone penetration (where the operating frequency exceeds the oblique MUF) are drawn as <b>dashed red lines</b> to visually warn you of the skip-zone.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">9. Regional Lightning & Convective Threat Engine (Hybrid NWS & Blitzortung Telemetry)</h2>
        <p>Thunderstorms and lightning static crashes (QRN) create intense wideband noise pulses that degrade receiver signal-to-noise ratios. POTA Prop combines official weather alerts with live stroke telemetry to monitor regional storms and protect station equipment:</p>

        <h3 style="color: #7ee787;">1. Hybrid Architecture: Instant Bootstrap & Live WebSocket Telemetry:</h3>
        <ul>
            <li><b>Instant NOAA NWS Convective Alerts & Popups:</b> On startup or whenever you change your Maidenhead operating grid, POTA Prop immediately queries active NOAA NWS Convective Alerts (Severe Thunderstorm, Tornado, Special Marine, and Flash Flood warnings) within your 750-mile monitoring radius. If your location falls exactly inside an active warning polygon, POTA Prop will trigger an active screen-interrupting warning popup!</li>
            <li><b>Live Blitzortung.org WebSocket Stream:</b> The application maintains an asynchronous background WebSocket connection to the <a href="https://www.blitzortung.org" style="color: #7ee787;">Blitzortung.org</a> community detection network, receiving live microsecond stroke telemetry worldwide.</li>
            <li><b>15-Minute Smooth Blending Warmup:</b> The engine smoothly blends NWS alert models into real-time Blitzortung strike counts over a 15-minute warmup curve:
                <br /><code>blended_rate = (1 - &alpha;) × NWS_rate + &alpha; × Live_rate</code>
                <br />Once the live buffer matures (&alpha; = 1.0), the engine operates purely on real-time strike density, spatial clustering, and observed flash rates.</li>
            <li><b>750-Mile (1,200 km) Regional Monitoring Radius:</b> Thunderstorm static can propagate up to ~750 miles via groundwave and night skywave. All strikes outside 750 miles are filtered out.</li>
            <li><b>60-Minute Sliding Buffer & Age Weighting:</b> Incoming strikes are retained in a 60-minute buffer with time-decay weighting (1.0 for &lt;10m, 0.70 for 10–20m, 0.45 for 20–30m, 0.20 for 30–60m).</li>
            <li><b>Spatial Density & Storm Cell Clustering:</b> Strikes are grouped spatially to compute exact distance, bearing, and strike rates (<code>strikes/min</code>) for each thunderstorm cell.</li>
        </ul>

        <h3 style="color: #7ee787;">2. Standardized 1-to-10 Lightning Threat & Safety Scale:</h3>
        <table border="0" cellpadding="5" cellspacing="0" style="color: #c9d1d9; font-size: 12px; margin-left: 6px; margin-bottom: 10px;">
            <tr style="color: #8b949e; border-bottom: 1px solid #30363d;">
                <th style="text-align: left; padding-right: 10px;">Level</th>
                <th style="text-align: left; padding-right: 12px;">Threat Category</th>
                <th style="text-align: left; padding-right: 14px;">Storm Proximity</th>
                <th style="text-align: left;">Station Safety & Operating Guidance</th>
            </tr>
            <tr>
                <td><b style="color: #2ea043;">Level 1</b></td>
                <td>Clear / Quiet</td>
                <td>&gt; 750 miles</td>
                <td>Normal operating conditions. Low background noise on all bands.</td>
            </tr>
            <tr>
                <td><b style="color: #3fb950;">Level 2–3</b></td>
                <td>Very Low / Low</td>
                <td>350–750 miles</td>
                <td>Distant storm cells. Negligible background sferics; 20m and above unaffected.</td>
            </tr>
            <tr>
                <td><b style="color: #d29922;">Level 4–5</b></td>
                <td>Moderate / Elevated</td>
                <td>140–350 miles</td>
                <td>Regional storm clusters. Noticeable static crashes on 40m/80m.</td>
            </tr>
            <tr>
                <td><b style="color: #f0883e;">Level 6</b></td>
                <td>Notable</td>
                <td>85–140 miles</td>
                <td>Frequent static crashes on lower bands. Monitor regional storm movement.</td>
            </tr>
            <tr>
                <td><b style="color: #e06c3a;">Level 7</b></td>
                <td>Storms Nearby</td>
                <td>45–85 miles</td>
                <td>Heavy QRN on 160m–40m. Consider shifting to higher bands (20m–10m).</td>
            </tr>
            <tr>
                <td><b style="color: #da3633;">Level 8</b></td>
                <td>Close Storms / Frequent</td>
                <td>20–45 miles (or frequent)</td>
                <td>Heavy local QRN (S7–S9 static). Storms approaching — prepare to shut down.</td>
            </tr>
            <tr>
                <td><b style="color: #f85149;">Level 9</b></td>
                <td>Very Close Proximity</td>
                <td>8–20 miles</td>
                <td><b>DISCONNECT ADVISORY:</b> Thunderstorms within 20 miles. High risk of electrostatic induction. Disconnect feedlines and rotor cables.</td>
            </tr>
            <tr>
                <td><b style="color: #ff2a55;">Level 10</b></td>
                <td>Immediate Hazard</td>
                <td>&lt; 8 miles</td>
                <td><b>DANGER:</b> Lightning in immediate vicinity! Unplug all rigs, disconnect feedlines, and disconnect AC power cords immediately.</td>
            </tr>
        </table>

        <h3 style="color: #7ee787;">3. Interactive Lightning Dashboard Card & Trajectory Motion Tracking:</h3>
        <p>The <b>Lightning</b> card in the top dashboard bar displays your current threat score and label. Hovering your mouse over the card reveals an extensive diagnostic popup showing:</p>
        <ul>
            <li><b>Nearest NWS Convective Alert:</b> Alert headline, distance, bearing, active strike count in the polygon, and time remaining until warning product expiration.</li>
            <li><b>Nearest Active Lightning Clusters & Trajectory Tracking (Motion / TOA):</b> Evaluates historical stroke centroids over time to derive storm ground speed (mph) and cardinal movement direction. If a storm cell is approaching your QTH (within ~35 miles CPA), it displays the estimated <b>Time of Arrival (TOA in minutes)</b> (e.g. <code>28 mph → NE (TOA 35m)</code>). Receding or lateral storms display <code>(TOA: NA)</code>.</li>
            <li><b>Regional Strike Totals:</b> Aggregate strike count and flash rate across the entire 750-mile monitoring radius.</li>
            <li><b>Band QRN Noise Surges:</b> Estimated static surge in dB for 160m, 80m, 40m, and 20m.</li>
        </ul>

        <h3 style="color: #7ee787;">4. Open-Meteo Local Weather & 12-Hour Hourly Forecast:</h3>
        <p>The <b>Local Weather</b> card on the top stats bar displays your current local temperature and weather condition icon (e.g. <code>72°F Partly Cloudy</code>). Hovering your mouse over the card opens a detailed 12-hour hourly forecast popup containing:</p>
        <ul>
            <li><b>Current Observations:</b> Temperature, condition description, and surface wind vector.</li>
            <li><b>12-Hour Hourly Forecast Table:</b> Displays upcoming hourly predictions for <b>Time (UTC)</b> in 24-hour format, <b>Temp (°F)</b>, <b>Condition</b> icon/description, and <b>Wind (mph &amp; direction)</b>.</li>
            <li><b>Attribution:</b> Weather data is provided by <a href="https://open-meteo.com/" style="color: #58a6ff;">Open-Meteo.com</a> (CC-BY 4.0).</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">10. Receiver Band Noise Floor Matrix & ITU-R P.372 Modeling (F6)</h2>
        <p>A station's ability to copy weak POTA activators depends directly on the receiver noise floor. POTA Prop implements a comprehensive, 11-band noise floor engine modeled after <b>ITU-R P.372-16</b> and real-time environmental telemetry:</p>

        <h3 style="color: #7ee787;">1. The Band Noise Dashboard Card & Modal Matrix (F6):</h3>
        <ul>
            <li><b>Band Noise Stat Card:</b> Located on the top stats bar next to the Lightning card. Displays quick noise readings on reference bands (e.g. <code>40m: S1 | 20m: S0</code>) with dynamic color coding (Green/Blue for quiet, Yellow/Orange for elevated noise, Red for stormy conditions).</li>
            <li><b>Opening the Matrix Window:</b> Click the <b>Band Noise</b> card, press <b>F6</b>, or select <i>View &rarr; Receiver Band Noise Floor Matrix (F6)</i> from the menu bar to open the full matrix dialog.</li>
        </ul>

        <h3 style="color: #7ee787;">2. ITU-R P.372 Noise Floor Components & Diurnal Modeling:</h3>
        <p>For each amateur band from 160m to 6m, POTA Prop calculates the individual noise components that combine to form the total antenna noise figure (F<sub>a</sub>):</p>
        <ul>
            <li><b>Base Atmospheric Noise (F<sub>atm</sub>) & Diurnal Day/Night Variation:</b> Atmospheric noise originates from tropical and regional lightning discharges propagating through the Earth-ionosphere waveguide.
                <ul>
                    <li><b>Daytime:</b> Solar radiation creates a dense D-layer (75 km), absorbing low-frequency skywaves and resulting in a lower atmospheric noise floor.</li>
                    <li><b>Nighttime:</b> The D-layer vanishes after sunset. Thunderstorm static from across the globe propagates with minimal absorption, causing nighttime noise on 160m and 80m to rise by <b>+10 to +20 dB (2 to 3+ S-units)</b>. POTA Prop models this solar diurnal curve based on local solar elevation at your QTH.</li>
                </ul>
            </li>
            <li><b>Lightning QRN Surge (&Delta;F<sub>QRN</sub>):</b> Real-time noise injected from convective storm cells within 750 miles based on live Blitzortung telemetry.</li>
            <li><b>Total Atmospheric Noise (F<sub>atm, total</sub>):</b> The combination of diurnal baseline noise and local thunderstorm surges: <code>F_atm,total = F_atm_base + &Delta;F_QRN</code>.</li>
            <li><b>Cosmic / Galactic Background Noise (F<sub>gal</sub>):</b> Extraterrestrial radio noise from the galactic plane, dominant on the upper HF and VHF bands: <code>F_gal = 52 - 23 log10(f_MHz)</code>.</li>
            <li><b>Man-Made Environmental Baseline (F<sub>man</sub>):</b> Standard quiet residential/rural man-made noise floor: <code>F_man = 53.6 - 28.6 log10(f_MHz)</code>.</li>
            <li><b>Total Antenna Noise Figure (F<sub>a</sub>):</b> The power-sum of all uncorrelated noise figures:
                <br /><code>F_a = 10 log10( 10^(F_atm,total / 10) + 10^(F_gal / 10) + 10^(F_man / 10) )</code></li>
            <li><b>Receiver Noise Power in Standard SSB Bandwidth (P<sub>noise</sub>):</b> Noise power in a standard 2,400 Hz communications receiver:
                <br /><code>P_noise (dBm) = -174 dBm/Hz + 10 log10(2400 Hz) + F_a = -140.2 dBm + F_a</code></li>
            <li><b>S-Meter Reading Calibration (IARU Standard):</b> Standard HF calibration where <b>S9 = -73 dBm (50 &mu;V)</b>, <b>6 dB per S-unit</b>, and <b>S0 = -127 dBm</b>:
                <br /><code>S-Units = (P_noise_dBm - (-127 dBm)) / 6.0 dB</code></li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">11. Link Budget, Antenna Elevation Gain & Signal-to-Noise Ratio (SNR)</h2>
        <p>POTA Prop calculates an RF link budget for every active spot using standard transmission equations:</p>

        <h3 style="color: #7ee787;">1. Path Loss Formulation (L<sub>b</sub>):</h3>
        <ul>
            <li><b>Free-Space Basic Transmission Loss (L<sub>bf</sub>):</b> <code>L_bf = 32.45 + 20 log10(f_MHz) + 20 log10(d_slant_km)</code></li>
            <li><b>ITU-R P.533 & NOAA D-RAP Ionospheric Absorption (L<sub>a</sub>):</b> Non-deviative D-layer absorption evaluating spherical obliquity factor <code>sec(&phi;_D)</code> through the 75 km layer combined with real-time NOAA SWPC D-RAP absorption grids: <code>L_a = 2 × N_hops × A_D × sec(&phi;_D) + L_DRAP</code>.</li>
            <li><b>Ground Reflection Loss (L<sub>g</sub>):</b> For multi-hop paths (2F2, 3F2), each intermediate ground reflection introduces ~3.0 dB loss: <code>L_g = (N_hops - 1) × 3.0 dB</code>.</li>
        </ul>

        <h3 style="color: #7ee787;">2. Dynamic Antenna Elevation Gain G(&Delta;, f):</h3>
        <p>Antenna gain depends on the launch takeoff angle (&Delta;) calculated for the path:</p>
        <ul>
            <li><code>G_tx(&Delta;, f)</code>: Evaluates the elevation radiation pattern of your selected antenna at angle &Delta;.</li>
            <li>For example, a beam at &Delta; = 12° provides +10.5 dBi; a vertical provides +5.0 dBi; a dipole provides +3.9 dBi; while at steep NVIS angles (&Delta; = 55°), the dipole provides +6.9 dBi while the vertical exhibits an overhead null (-4.3 dBi).</li>
        </ul>

        <h3 style="color: #7ee787;">3. Receiver Signal Power & Noise Floor:</h3>
        <ul>
            <li><b>Received Signal Power (S<sub>dBW</sub>):</b> <code>S = P_tx_dBW + G_tx(&Delta;, f) - L_b - 4.0 dB (portable activator offset)</code></li>
            <li><b>Total Receiver Noise Power (N<sub>dBW</sub>):</b> <code>N = -204 + 10 log10(BW_Hz) + F_a</code>, where <code>F_a</code> is the ITU-R P.372 antenna noise figure incorporating both diurnal atmospheric noise and regional lightning surges.</li>
            <li><b>Predicted SNR:</b> <code>SNR_dB = S_dBW - N_dBW</code>.</li>
            <li><b>Circuit Reliability (REL):</b> Modeled via log-normal error distribution:
                <br /><code>REL = 0.5 × [1 + erf((SNR - SNR_req) / (sqrt(2) × &sigma;_fading))] × 100%</code></li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">12. Space Weather Telemetry: NOAA Solar Flares, PSKReporter & QRT Detection</h2>
        <h3 style="color: #7ee787;">Geomagnetic Indices: Planetary K-Index vs. Planetary A-Index:</h3>
        <ul>
            <li><b>K-Index (0 to 9, 3-Hour Metric):</b> Measures geomagnetic activity. K &le; 2 is quiet; K &ge; 4 indicates disturbed conditions.</li>
            <li><b>A-Index (0 to 400, 24-Hour Cumulative Metric):</b> High A-index (A &ge; 25) reflects cumulative storminess that may reduce F2-layer critical frequencies.</li>
        </ul>

        <h3 style="color: #7ee787;">NOAA GOES Satellite Solar Flares & Radio Blackouts (R1 to R5):</h3>
        <p>POTA Prop monitors real-time 0.1–0.8nm X-ray flux from NOAA GOES satellites:</p>
        <ul>
            <li><b>M-Class Flares (R1/R2 Blackout):</b> Applies a <b>-15 to -25 point adjustment</b> on daylight HF paths due to increased D-layer absorption.</li>
            <li><b>X-Class Flares (R3/R4/R5 Severe Blackout):</b> Applies a <b>-40 to -50 point adjustment</b> to reflect radio blackout conditions.</li>
        </ul>

        <h3 style="color: #7ee787;">Automated QRT Detection:</h3>
        <p>When spotters post comments indicating an activator has shut down (e.g. <i>QRT</i>, <i>going QRT</i>, <i>off air</i>, <i>73 QRT</i>), the score is set to <b>0</b> and the status is marked as <b>Activator QRT (Off the air)</b>.</p>

        <h3 style="color: #7ee787;">IMO Meteor Scatter Telemetry:</h3>
        <p>POTA Prop actively scrapes the <b>International Meteor Organization (IMO)</b> for live Meteor Shower activity, Zenithal Hourly Rates (ZHR), and shower peak classifications. This is used to model massive +15 point Sporadic-E enhancements on 6m and 10m bands when ZHR exceeds 15 meteors per hour.</p>

        <h3 style="color: #7ee787;">Live Multi-Node PSKReporter Telemetry & Mode Penalty Logic:</h3>
        <p>POTA Prop incorporates a massive background telemetry engine that continuously interrogates the <b>PSKReporter Network</b> to detect empirical proof of band openings, completely overriding mathematical skip-zones if live propagation is occurring:</p>
        <ul>
            <li><b>Multi-Node Proxy Array:</b> You can configure a comma-separated list of regional super-nodes (e.g. <code>W3LPL, K3LR, K9ZO</code>) in the settings. The engine performs round-robin background polling to harvest regional FT8/FT4 decodes across all bands.</li>
            <li><b>Targeted Activator Sweeps:</b> The engine actively sweeps digital POTA activators every 60 seconds to verify if regional spotters are successfully decoding them.</li>
            <li><b>Mode Penalty Logic:</b> The engine evaluates the Signal-to-Noise Ratio (SNR) of these live digital decodes to estimate cross-mode viability. Exceptionally strong digital decodes (e.g. >= 0dB) provide massive empirical boosts (+15 points) for SSB targets, while weak decodes are scaled appropriately for CW or ignored for SSB to maintain realistic expectations.</li>
            <li><b>FIFO Status Message Queue:</b> All of these massive background telemetry events feed into an elegant, non-blocking FIFO queue on the bottom status bar, displaying items cleanly rotating every 5 seconds to prevent overwhelming you.</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">13. Tooltip Propagation Outcomes & Telemetry Reference Guide</h2>
        <p>When you hover your mouse over any <b>Score</b> badge or row in the table, POTA Prop displays a diagnostic popup. Below is a reference of the telemetry lines:</p>
        
        <h3 style="color: #7ee787;">Telemetry Elements:</h3>
        <ul>
            <li><b>Ray Path:</b> Identifies the dominant ray mode (e.g., <code>1F2</code>, <code>2F2</code>, <code>1E</code>), launch elevation angle &Delta; (e.g. <code>Elev 8.2°</code>), and total path loss (e.g. <code>Loss 128.4 dB</code>).</li>
            <li><b>Est SNR:</b> The predicted signal-to-noise ratio in dB relative to mode decoding thresholds (e.g. <code>Est SNR: +8.5 dB</code>).</li>
            <li><b>⚡ Lightning QRN Surge:</b> Displays active thunderstorm noise surges (e.g. <code>⚡ Lightning QRN Surge: +14.2 dB</code>).</li>
            <li><b>Est MUF:</b> The oblique Maximum Usable Frequency for the path (e.g. <code>Est MUF: 21.4 MHz</code>).</li>
        </ul>

        <h3 style="color: #7ee787;">Path Summary Outcomes:</h3>
        <ul>
            <li><b>Optimal Skywave (High Success):</b> Operating frequency is within the favorable MUF window, path loss is moderate, and SNR is strong.</li>
            <li><b>Good Propagation Path:</b> A reliable skywave path with favorable MUF and manageable path loss.</li>
            <li><b>Fair / Marginal Path:</b> The path is open, but signal levels are close to the noise floor.</li>
            <li><b>Closed (Skip Zone / Penetration: Freq > Oblique MUF):</b> Frequency exceeds the oblique critical frequency; radio wave penetrates the ionosphere into outer space.</li>
            <li><b>Heavy Daytime D-Layer Absorption:</b> Solar radiation causes D-layer attenuation on lower bands (160m, 80m, 40m).</li>
            <li><b>Beyond VHF Horizon:</b> Distance on 2m/70cm exceeds the line-of-sight / tropospheric radio horizon (~150 km).</li>
            <li><b>6m Summer Sporadic-E Skip Opening:</b> Seasonal E-layer skip openings on 6m.</li>
            <li><b>Activator QRT (Off the air):</b> Activator station has shut down (QSO score = 0).</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">14. Real-time Propagation Summary</h2>
        <p>Click the <b>Propagation Summary</b> button on the bottom action bar to open a dedicated dispatch synthesizing all real-time telemetry into an objective, technical narrative discussion:</p>
        
        <h3 style="color: #7ee787;">Summary Narrative Sections:</h3>
        <ul>
            <li><b>.SYNOPSIS...:</b> High-level solar, ionospheric, and geomagnetic conditions (Solar Flux Index, Sunspot Number, Kp/Ap indices, solar wind velocity/density, and D-RAP X-ray absorption).</li>
            <li><b>.BAND CONDITIONS & OPERATING OUTLOOK...:</b> Band-by-band breakdown across Higher HF (10m–15m), Mid HF (17m–20m), Lower HF (30m–160m), and VHF (6m–2m).</li>
            <li><b>.SHORT-TERM 3-DAY PROPAGATION OUTLOOK (NOAA SWPC)...:</b> Numerical and narrative forecast of 10.7cm Solar Flux, Planetary A-Index ($A_p$), peak Kp, storm scales ($G0$–$G5$), M/X-class flare probabilities, and polar radiation storm risks.</li>
            <li><b>.EXTENDED 27-DAY SOLAR CYCLE & RECURRENT OUTLOOK...:</b> 27-day solar rotation projections of 7-day average SFI, optimal upper-band DX windows, and recurrent coronal hole geomagnetic storm dates.</li>
            <li><b>.SPACE WEATHER & SPECIAL PHENOMENA...:</b> NOAA SWPC Auroral oval boundary dynamics, trans-polar flutter risks, and active meteor shower scatter bursts.</li>
            <li><b>.LOCAL QRN & THUNDERSTORM HAZARDS...:</b> Real-time Blitzortung lightning proximity, Global 3-Day Convective & QRN Outlook (Precipitation %, Thunderstorm risk %, peak CAPE in J/kg, and static crash severity), and Seasonal QRN Climatology (month-by-month and hemispheric noise-floor trends).</li>
            <li><b>.POTA ACTIVITY & PROPAGATION HOTSPOTS...:</b> Total active park activations worldwide, band distribution breakdown, and regional cluster concentrations.</li>
            <li><b>.RECOMMENDED OPERATING STRATEGY...:</b> Practical operating advice for optimal band selection, receiver noise blanking, and hunter QSO rates.</li>
        </ul>
        <p>Click <b>📋 Copy to Clipboard</b> in the summary window to copy the full dispatch for station logs or sharing with fellow operators.</p>

        <hr style="border: 1px solid #30363d;" />
        
        <h2 style="color: #58a6ff;">15. Open Source License</h2>
        <p>This project is licensed under the <b>GNU General Public License v3.0 (GPLv3)</b>.</p>
        <p>You are free to use, modify, and distribute this software for amateur radio purposes, provided that any derivative works are also open-source and released under the same GPLv3 license.</p>

        <br />
        <h1 style="color: #f85149; font-size: 18px; margin-top: 16px; border-bottom: 2px solid #f85149; padding-bottom: 6px;">PART III: FIELD SAFETY DISCLAIMER & LIMITATION OF LIABILITY</h1>

        <p style="color: #ffa657; font-weight: bold; font-size: 13px;">PLEASE READ CAREFULLY BEFORE USING THIS SOFTWARE IN THE FIELD:</p>
        <p><b>1. Recreational & Educational Purpose Only:</b> POTA Prop is provided strictly for recreational amateur radio operating, propagation modeling, and educational interest. All weather forecasts, lightning cluster motion tracking, Time of Arrival (TOA) estimates, NOAA NWS convective alert warnings, band noise calculations, and ionospheric propagation scores are generated by automated computer models and third-party network feeds.</p>
        
        <p><b>2. NOT FOR LIFE SAFETY OR EMERGENCY USE:</b> This software must <b>NEVER</b> be relied upon as a primary source for life safety decisions, weather hazard prediction, lightning protection, or emergency field planning. Severe weather, lightning strikes, electrostatic discharges, and atmospheric conditions can change, intensify, or strike rapidly without warning or detection by remote sensors.</p>
        
        <p><b>3. Operator Field Safety Responsibility:</b> Amateur radio operators operating portable in parks or at fixed station locations are solely responsible for maintaining situational awareness, observing local environmental conditions, and taking appropriate safety precautions (including immediately shutting down, disconnecting antenna feedlines, grounding equipment, and seeking proper shelter during lightning activity).</p>
        
        <p><b>4. Complete Limitation of Liability:</b> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. IN NO EVENT SHALL THE DEVELOPER(S), AUTHOR(S), OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING BUT NOT LIMITED TO PERSONAL INJURY, LOSS OF LIFE, PROPERTY DAMAGE, EQUIPMENT DAMAGE, OR INACCURACIES) ARISING OUT OF OR IN CONNECTION WITH THE USE, RELIANCE UPON, OR INABILITY TO USE THIS SOFTWARE.</p>
        """

        docs_text.setText(docs_html)
        c_layout.addWidget(docs_text)

        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("Close")

        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)


class PropagationSummaryDialog(QDialog):
    """
    Dedicated window for the comprehensive Propagation Summary.
    """
    def __init__(self, telemetry: dict, parent=None):
        super().__init__(parent)
        self.telemetry = telemetry
        self.setWindowTitle("Propagation Summary")
        self.resize(840, 640)
        self.setMinimumSize(680, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Title bar
        hdr_layout = QHBoxLayout()
        title_lbl = QLabel("📡 Propagation & Operating Summary")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()
        layout.addLayout(hdr_layout)

        # Text display area
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(True)
        self.txt_display.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Consolas', 'Courier New', 'DejaVu Sans Mono', monospace;
                font-size: 13px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Render summary
        self.summary_text = generate_propagation_summary(self.telemetry)
        self.txt_display.setPlainText(self.summary_text)

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.btn_copy = QPushButton("📋 Copy to Clipboard")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        btn_layout.addWidget(self.btn_copy)

        btn_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def copy_to_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        text = self.txt_display.toPlainText()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self.btn_copy.setText("✓ Copied!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.btn_copy.setText("📋 Copy to Clipboard"))




class SyncWorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

class SyncWorker(QRunnable):
    def __init__(self, id_token: str, save_path: str):
        super().__init__()
        self.id_token = id_token
        self.save_path = save_path
        self.signals = SyncWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            hunted = fetch_hunter_parks_from_api(self.id_token, self.save_path)
            try:
                self.signals.finished.emit(hunted)
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass

class SpotWorkerSignals(QObject):
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

class SpotWorker(QRunnable):
    def __init__(self, payload: dict, id_token: Optional[str]):
        super().__init__()
        self.payload = payload
        self.id_token = id_token
        self.signals = SpotWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            success = submit_spot_to_api(self.payload, self.id_token)
            try:
                if success:
                    self.signals.finished.emit(True)
                else:
                    self.signals.error.emit("Failed to submit spot.")
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass

class SpotDialog(QDialog):
    def __init__(self, activator: str, reference: str, frequency: str, mode: str, my_call: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spot Activator")
        self.setMinimumWidth(350)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)

        # Form Layout
        form_layout = QFormLayout()
        
        self.txt_activator = QLineEdit(activator)
        form_layout.addRow("Activator:", self.txt_activator)
        
        self.txt_spotter = QLineEdit(my_call)
        form_layout.addRow("Spotter (You):", self.txt_spotter)
        
        self.txt_freq = QLineEdit(frequency)
        form_layout.addRow("Frequency (kHz):", self.txt_freq)
        
        self.txt_mode = QLineEdit(mode)
        form_layout.addRow("Mode:", self.txt_mode)
        
        self.txt_ref = QLineEdit(reference)
        form_layout.addRow("Park Reference:", self.txt_ref)
        
        self.txt_comments = QLineEdit()
        self.txt_comments.setPlaceholderText("Optional comments...")
        form_layout.addRow("Comments:", self.txt_comments)
        
        self.chk_mark_worked = QCheckBox("Marked Worked")
        self.chk_mark_worked.setChecked(True)
        form_layout.addRow("", self.chk_mark_worked)
        
        layout.addLayout(form_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_submit = QPushButton("Submit Spot")
        self.btn_submit.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_submit)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def get_spot_data(self):
        return {
            "activator": self.txt_activator.text().strip().upper(),
            "spotter": self.txt_spotter.text().strip().upper(),
            "frequency": self.txt_freq.text().strip(),
            "mode": self.txt_mode.text().strip().upper(),
            "reference": self.txt_ref.text().strip().upper(),
            "source": "POTA Prop",
            "comments": self.txt_comments.text().strip()
        }


import concurrent.futures

class HeatmapCacheService(QThread):
    status_updated = pyqtSignal(str, str, str) # text, tooltip, color
    cache_ready = pyqtSignal(str, str, str) # band, mode, json_data
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.heatmap_cache = {} # (band, mode) -> json_data
        self.running = True
        self.parent_app = parent
        
        self.bands_to_cache = ["20m", "40m", "17m", "15m", "10m", "80m", "60m", "30m", "12m", "6m", "160m"]
        self.modes_to_cache = ["SSB", "CW", "FT8", "DATA"]
        
        self.current_updating_band = None
        self.last_update_time = 0.0
        
    def _get_tooltip(self):
        lines = []
        for b in self.bands_to_cache:
            if b == self.current_updating_band:
                lines.append(f"<span style='color:#7ee787'>{b}: Updating...</span>")
            elif (b, "SSB") in self.heatmap_cache:
                lines.append(f"<span style='color:#8b949e'>{b}: Ready</span>")
            else:
                lines.append(f"<span style='color:#f85149'>{b}: Waiting</span>")
        return "<br>".join(lines)
        
    def _emit_status(self, text):
        color = "#7ee787" # Green default
        if self.current_updating_band is None:
            if self.last_update_time == 0.0:
                color = "#8b949e" # Grey while waiting 60s
            else:
                elapsed = time.time() - self.last_update_time
                if elapsed > 1800: # 30 mins
                    color = "#f85149" # Red
                elif elapsed > 900: # 15 mins
                    color = "#d29922" # Yellow
        self.status_updated.emit(text, self._get_tooltip(), color)
        
    def run(self):
        # Wait 60 seconds after startup as requested by the user
        self._emit_status("Maps: Gathering data... (waiting 1m)")
        for _ in range(60):
            if not self.running:
                return
            time.sleep(1.0)
            
        from propagation_engine import calculate_heatmap_matrix_mp
        
        while self.running:
            for band in self.bands_to_cache:
                start_time = time.time()
                self.current_updating_band = band
                self._emit_status(f"Maps: Updating {band}...")
                
                # Fetch inputs safely from main window
                from propagation_engine import maidenhead_to_latlon
                current_grid = getattr(self.parent_app, 'current_grid', "")
                home_lat, home_lon = 0.0, 0.0
                if current_grid:
                    h_lat, h_lon = maidenhead_to_latlon(current_grid)
                    if h_lat is not None and h_lon is not None:
                        home_lat, home_lon = h_lat, h_lon
                        
                tx_power = getattr(self.parent_app, 'tx_power', 100.0)
                antenna_type = getattr(self.parent_app, 'antenna_type', 'dipole')
                solar_weather = getattr(self.parent_app, 'solar_weather', None)
                lightning = getattr(self.parent_app, 'lightning_summary', None)
                regional_matrix = getattr(self.parent_app, 'regional_matrix', None)
                
                if not home_lat or not home_lon or not solar_weather:
                    time.sleep(5)
                    continue

                # Run multiprocessing for all modes of this band
                futures = {}
                low_mem = getattr(self.parent_app, 'low_memory_mode', False)
                try:
                    import multiprocessing
                    ctx = multiprocessing.get_context('spawn')
                    workers = 1 if low_mem else min(5, os.cpu_count() or 4)
                    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
                        for mode in self.modes_to_cache:
                            mapping = {
                                "160m": 1850.0, "80m": 3900.0, "60m": 5357.0, "40m": 7200.0,
                                "30m": 10120.0, "20m": 14200.0, "17m": 18100.0, "15m": 21300.0,
                                "12m": 24900.0, "10m": 28500.0, "6m": 50150.0
                            }
                            freq = mapping.get(band, 14200.0)
                            f = executor.submit(
                                calculate_heatmap_matrix_mp,
                                home_lat, home_lon, band, mode, freq,
                                solar_weather, tx_power, antenna_type, lightning, regional_matrix
                            )
                            futures[f] = mode
                            
                        for f in concurrent.futures.as_completed(futures):
                            if not self.running:
                                break
                            mode = futures[f]
                            try:
                                json_data = f.result()
                                self.heatmap_cache[(band, mode)] = json_data
                                self.cache_ready.emit(band, mode, json_data)
                            except Exception as e:
                                logging.error(f"Error caching {band} {mode}: {e}")
                except Exception as e:
                    logging.error(f"ProcessPoolExecutor failed: {e}")
                
                if not self.running:
                    break
                    
                self.current_updating_band = None
                self.last_update_time = time.time()
                self._emit_status(f"Maps: < 1m")
                
                # Space out bands by 1 minute (or 15 mins in low memory mode)
                sleep_time = 900 if low_mem else 60
                for _ in range(sleep_time):
                    if not self.running:
                        break
                    time.sleep(1.0)
                    
    def stop(self):
        self.running = False
        self.wait()

class MapPropagationWorkerSignals(QObject):
    finished = pyqtSignal(str, str, str) # band, mode, json_data

class MapPropagationWorker(QRunnable):
    def __init__(self, home_lat: float, home_lon: float, home_grid: str, band: str, mode: str, solar_weather: SolarWeather, tx_power: float, antenna_type: str, lightning: Optional[RegionalLightningSummary], regional_matrix: Optional[RegionalPathMatrix], live_spots: List[Dict]):
        super().__init__()
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.home_grid = home_grid
        self.band = band
        self.mode = mode
        self.solar_weather = solar_weather
        self.tx_power = tx_power
        self.antenna_type = antenna_type
        self.lightning = lightning
        self.regional_matrix = regional_matrix
        self.live_spots = live_spots
        self.signals = MapPropagationWorkerSignals()
        
    def get_band_freq(self, band):
        mapping = {
            "160m": 1850.0, "80m": 3900.0, "60m": 5357.0, "40m": 7200.0,
            "30m": 10120.0, "20m": 14200.0, "17m": 18100.0, "15m": 21300.0,
            "12m": 24900.0, "10m": 28500.0, "6m": 50150.0
        }
        return mapping.get(band, 14200.0)

    @pyqtSlot()
    def run(self):
        try:
            heatmap_data = []
            if not self.home_lat or not self.home_lon:
                self.signals.finished.emit(self.band, self.mode, "[]")
                return
                
            freq = self.get_band_freq(self.band)

            # Step by 1 degree lat and 2 degrees lon for true Maidenhead grid resolution
            # Aligns perfectly to Maidenhead boundaries
            for lat in range(-90, 90, 1):
                for lon in range(-180, 180, 2):
                    # Calculate probability at the exact center of the 1x2 block
                    center_lat = lat + 0.5
                    center_lon = lon + 1.0
                    
                    from propagation_engine import latlon_to_maidenhead
                    target_grid = latlon_to_maidenhead(center_lat, center_lon, precision=4)

                    res = calculate_qso_probability(
                        home_lat=self.home_lat,
                        home_lon=self.home_lon,
                        target_lat=center_lat,
                        target_lon=center_lon,
                        target_grid=target_grid,
                        freq_khz=freq,
                        band=self.band,
                        mode=self.mode,
                        solar_weather=self.solar_weather,
                        tx_power_watts=self.tx_power,
                        antenna_type=self.antenna_type,
                        lightning_summary=self.lightning,
                        regional_matrix=self.regional_matrix
                    )
                    if res and res.probability_pct >= 0:
                        # Pass the SW corner (lat, lon) to the map so it can draw the 2x4 degree box accurately
                        heatmap_data.append([lat, lon, res.probability_pct / 100.0])

            self.signals.finished.emit(self.band, self.mode, json.dumps(heatmap_data))
        except Exception as e:
            logging.warning(f"Error in MapPropagationWorker: {e}")

class GaussianBlendWorkerSignals(QObject):
    finished = pyqtSignal(str, str, str) # band, mode, json_data

class GaussianBlendWorker(QRunnable):
    def __init__(self, band: str, mode: str, cached_json: str, live_spots: List[Dict]):
        super().__init__()
        self.band = band
        self.mode = mode
        self.cached_json = cached_json
        self.live_spots = live_spots
        self.signals = GaussianBlendWorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            import json, math
            data = json.loads(self.cached_json)
            
            def haversine(lat1, lon1, lat2, lon2):
                R = 6371.0 # Earth radius in km
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
                return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

            if self.live_spots:
                for point in data:
                    lat, lon, base_prob = point[0], point[1], point[2]
                    blended_prob = base_prob * 100.0
                    
                    max_spot_influence = 0.0
                    for spot in self.live_spots:
                        if abs(lat - spot['lat']) > 25.0: continue
                        
                        dist_km = haversine(lat, lon, spot['lat'], spot['lon'])
                        if dist_km <= 3000.0:
                            active_score = spot['score']
                            w = math.exp(-(dist_km**2) / (2 * 300.0**2))
                            influence = active_score * w
                            if influence > max_spot_influence:
                                max_spot_influence = influence
                                
                    blended_prob = max(blended_prob, max_spot_influence)
                    point[2] = blended_prob / 100.0

            self.signals.finished.emit(self.band, self.mode, json.dumps(data))
        except Exception as e:
            logging.warning(f"Error in GaussianBlendWorker: {e}")
            self.signals.finished.emit(self.band, self.mode, self.cached_json)

class MapBackend(QObject):
    filterChanged = pyqtSignal(str, str)
    graylineChanged = pyqtSignal(bool)
    fullscreenToggle = pyqtSignal()

    @pyqtSlot(str, str)
    def onFilterChanged(self, band, mode):
        self.filterChanged.emit(band, mode)

    @pyqtSlot(bool)
    def onGraylineChanged(self, show_grayline):
        self.graylineChanged.emit(show_grayline)

    @pyqtSlot()
    def toggleFullscreen(self):
        self.fullscreenToggle.emit()


class MapWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("POTA Prop - Live Map")
        self.resize(1050, 750)
        self.parent_app = parent

        self.web_view = QWebEngineView(self)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.setCentralWidget(self.web_view)

        self.backend = MapBackend()
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.backend)
        self.web_view.page().setWebChannel(self.channel)

        self.backend.filterChanged.connect(self.on_filter_changed)
        self.backend.graylineChanged.connect(self.on_grayline_changed)
        self.backend.fullscreenToggle.connect(self.toggle_fullscreen)
        self.web_view.loadFinished.connect(self.on_load_finished)

        # Shortcuts
        self.shortcut_fs = QShortcut(QKeySequence("F11"), self)
        self.shortcut_fs.activated.connect(self.toggle_fullscreen)
        self.shortcut_esc = QShortcut(QKeySequence("Esc"), self)
        self.shortcut_esc.activated.connect(self.showNormal)

        map_path = get_resource_path("map.html")
        self.web_view.setUrl(QUrl.fromLocalFile(map_path))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def on_load_finished(self, ok):
        if ok and self.parent_app:
            home_lat, home_lon = maidenhead_to_latlon(self.parent_app.current_grid)
            if home_lat is not None and home_lon is not None:
                self.web_view.page().runJavaScript(f"initMap({home_lat}, {home_lon});")
            active_band = getattr(self.parent_app, 'map_band', '20m')
            active_mode = getattr(self.parent_app, 'map_mode', 'SSB')
            if active_band in ("All", "All Bands", "Other"):
                active_band = "20m"
            if active_mode in ("All", "All Modes"):
                active_mode = "SSB"
            self.set_filter_state(active_band, active_mode)
            self.parent_app.push_all_data_to_map()

    def set_filter_state(self, band, mode):
        self.web_view.page().runJavaScript(f"if (typeof window.setFilterState === 'function') window.setFilterState('{band}', '{mode}');")

    def on_filter_changed(self, band, mode):
        if self.parent_app:
            self.parent_app.on_web_filter_changed(band, mode)

    def on_grayline_changed(self, show_grayline):
        if self.parent_app:
            self.parent_app.on_web_grayline_changed(show_grayline)

    def update_spots(self, spots_data):
        escaped_json = json.dumps(spots_data)
        self.web_view.page().runJavaScript(f"if (typeof window.updateSpots === 'function') window.updateSpots({escaped_json});")

    def update_heatmap(self, heatmap_json_str):
        self.web_view.page().runJavaScript(f"if (typeof window.updateHeatmap === 'function') window.updateHeatmap({heatmap_json_str});")

    def update_grayline(self, lines_data):
        escaped_json = json.dumps(lines_data)
        self.web_view.page().runJavaScript(f"if (typeof window.updateGrayline === 'function') window.updateGrayline({escaped_json});")

    def update_aurora(self, lines_data):
        escaped_json = json.dumps(lines_data)
        self.web_view.page().runJavaScript(f"if (typeof window.updateAurora === 'function') window.updateAurora({escaped_json});")

    def update_lightning(self, cells_data):
        escaped_json = json.dumps(cells_data)
        self.web_view.page().runJavaScript(f"if (typeof window.updateLightning === 'function') window.updateLightning({escaped_json});")

    def update_band_counts(self, counts_data):
        escaped_json = json.dumps(counts_data)
        self.web_view.page().runJavaScript(f"if (typeof window.updateBandCounts === 'function') window.updateBandCounts({escaped_json});")

    def update_cache_status(self, cache_status):
        escaped_json = json.dumps(cache_status)
        self.web_view.page().runJavaScript(f"if (typeof window.updateCacheStatus === 'function') window.updateCacheStatus({escaped_json});")

    def set_last_update(self, time_str):
        self.web_view.page().runJavaScript(f"if (typeof window.setLastUpdate === 'function') window.setLastUpdate('{time_str}');")

    def closeEvent(self, event):
        super().closeEvent(event)



class POTAPropApp(QMainWindow):
    browser_filter_signal = pyqtSignal(str, str, bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("POTA Prop")

        self.resize(1150, 720)
        self.setMinimumSize(950, 560)

        self.threadpool = QThreadPool()
        self._active_workers: List[QRunnable] = []
        self.csv_path = DEFAULT_HUNTER_CSV_PATH
        self.hunted_parks: Dict[str, HuntedPark] = {}
        self.active_spots: List[ActiveSpot] = []
        self.compared_spots: List[ComparedSpot] = []
        self.psk_spots = []
        self.regional_matrix = None
        self.solar_weather = SolarWeather()

        self.authenticator = POTAAuthenticator()
        self.authenticator.auth_state_changed.connect(self.on_auth_state_changed)
        
        self.map_window = None
        self.map_band = "20m"
        self.map_mode = "SSB"
        self.browser_filter_signal.connect(self.handle_browser_filter_changed)
        self.is_chromebook = is_chromebook_crostini()
        
        # Start local HTTP Map Server across all platforms for seamless browser support / fallback
        resources_dir = get_resource_path(".")
        self.map_server = MapServerManager(resources_dir)
        self.map_server.set_filter_callback(lambda b, m, g: self.browser_filter_signal.emit(b, m, g))
        self.map_server.start()

        self.map_timer = QTimer(self)
        self.map_timer.setInterval(600_000) # 10 minutes
        self.map_timer.timeout.connect(self.on_map_timer_tick)

        # Settings, Operator Call, Grid, Station, P2P Mode, and Filters
        settings = QSettings("POTA", "HunterComparator")
        self.map_render_mode = str(settings.value("map_render_mode", MAP_RENDER_AUTO)).strip().lower()
        if self.map_render_mode not in (MAP_RENDER_AUTO, MAP_RENDER_QT, MAP_RENDER_BROWSER):
            self.map_render_mode = MAP_RENDER_AUTO
        self.rbn_nodes_str = settings.value("rbn_nodes_str", settings.value("rbn_node", "W1AW", type=str), type=str)
        self.rbn_nodes_list = [c.strip().upper() for c in self.rbn_nodes_str.split(',') if c.strip()]
        if not self.rbn_nodes_list:
            self.rbn_nodes_list = ["W1AW"]
        self._current_psk_node_idx = 0
        self.csv_path = str(settings.value("csv_path", DEFAULT_HUNTER_CSV_PATH)).strip() or DEFAULT_HUNTER_CSV_PATH
        self.my_call = str(settings.value("my_call", "")).strip().upper()
        self.home_grid = str(settings.value("home_grid", DEFAULT_HOME_GRID)).strip().upper() or DEFAULT_HOME_GRID
        self.current_grid = self.home_grid
        self.show_tooltips = settings.value("show_tooltips", True, type=bool)
        val = settings.value("low_memory_mode", False)
        self.low_memory_mode = (str(val).lower() == 'true') if isinstance(val, str) else bool(val)
        self.p2p_mode = settings.value("p2p_mode", False, type=bool)
        self.p2p_my_park = str(settings.value("p2p_my_park", "")).strip().upper()
        self.p2p_my_park_name = ""
        self.tx_power = float(settings.value("tx_power", DEFAULT_TX_POWER_WATTS))
        self.antenna_type = str(settings.value("antenna_type", DEFAULT_ANTENNA_TYPE)).strip()
        self.filter_status_idx = 0  # Always start with 'All' filter
        self.filter_dx_idx = settings.value("filter_dx_idx", 0, type=int)
        self.filter_band = str(settings.value("filter_band", "All Bands")).strip()
        self.filter_mode = str(settings.value("filter_mode", "All Modes")).strip()
        self.refresh_interval_idx = settings.value("refresh_interval_idx", 2, type=int)
        saved_worked = settings.value("manually_worked_parks", {})
        self.manually_worked_parks = WorkedParksTracker()
        today_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if isinstance(saved_worked, dict):
            for k, v in saved_worked.items():
                if k:
                    self.manually_worked_parks.add(str(k).strip().upper(), str(v).strip() if v else today_utc_str)
        elif isinstance(saved_worked, list):
            for x in saved_worked:
                if x:
                    self.manually_worked_parks.add(str(x).strip().upper(), today_utc_str)

        self._last_evaluated_utc_date = today_utc_str
        self.solar_weather = SolarWeather()
        self.lightning_summary: Optional[RegionalLightningSummary] = None
        self.acknowledged_nws_warnings: set = set()
        self._is_fetching = False
        self.spot_cache = {}

        self.last_pota_fetch_time = 0.0
        self.last_psk_fetch_time = 0.0
        self.last_swpc_fetch_time = 0.0
        self.last_wx_fetch_time = 0.0
        self.last_ltng_fetch_time = 0.0
        self.last_aurora_fetch_time = 0.0
        self.aurora_lines = []

        # POTA Spots Auto Refresh Timer (Interval set by combo box)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.fetch_spots)

        # NOAA Space Weather Timer (20 minutes)
        self.solar_timer = QTimer(self)
        self.solar_timer.timeout.connect(self.fetch_solar)
        self.solar_timer.start(1_200_000)
        QTimer.singleShot(10000, self.fetch_solar)  # SWPC at 10s

        # NOAA Aurora Oval Timer (15 minutes)
        self.aurora_timer = QTimer(self)
        self.aurora_timer.timeout.connect(self.fetch_aurora)
        self.aurora_timer.start(900_000)
        QTimer.singleShot(8000, self.fetch_aurora)  # Aurora at 8s

        # Lightning Timer (5 seconds) - Polls local background websocket
        self.lightning_timer = QTimer(self)
        self.lightning_timer.timeout.connect(self.fetch_lightning)
        self.lightning_timer.start(5_000)
        
        # Periodic Weather Refresh Timer (every 15 minutes)
        self.weather_summary: Optional[WeatherForecastSummary] = None
        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(lambda: self.refresh_weather_display(force_refresh=True))
        self.weather_timer.start(900000)  # 15 minutes
        QTimer.singleShot(30000, lambda: self.refresh_weather_display(force_refresh=True)) # WX at 30s
        
        # PSK Reporter / RBN Nodes Timer
        self.psk_timer = QTimer(self)
        self.psk_timer.timeout.connect(self.fetch_psk_spots)
        interval = max(60000, 900000 // max(1, len(self.rbn_nodes_list)))
        self.psk_timer.start(interval)
        QTimer.singleShot(15000, self.fetch_psk_spots)  # PSK at 15s

        # Targeted Activator PSK Polling
        self.activator_psk_queue = []
        self.activator_psk_cache = {}
        self.activator_psk_timer = QTimer(self)
        self.activator_psk_timer.timeout.connect(self.process_activator_psk_queue)
        self.activator_psk_timer.start(60000)  # Check queue every 60 seconds





        # UTC Day 00Z Rollover Timer (checks every 15s for 00Z day boundary crossing)
        self.utc_rollover_timer = QTimer(self)
        self.utc_rollover_timer.timeout.connect(self.check_utc_day_rollover)
        self.utc_rollover_timer.start(15000)

        # Live UTC Clock Timer (updates every 1000ms)
        self.utc_clock_timer = QTimer(self)
        self.utc_clock_timer.timeout.connect(self.update_utc_clock)
        self.utc_clock_timer.start(1000)

        self.weather_summary: Optional[WeatherForecastSummary] = None

        self.init_ui()
        self.update_utc_clock()

        # Explicitly initialize auto-refresh timer with saved combo interval
        self.on_refresh_interval_changed(self.combo_refresh.currentIndex())

        # Restore saved window geometry if present
        saved_geom = settings.value("window_geometry")
        if saved_geom:
            self.restoreGeometry(saved_geom)

        self.load_initial_csv()
        self.recompute_comparisons()
        
        # Prioritize fetching active POTA spots immediately on startup
        self.fetch_spots()

    def update_widget_history(self, lbl: QLabel, msg: str):
        if not hasattr(lbl, '_history'):
            lbl._history = []
            
        from datetime import datetime
        now_str = datetime.now().strftime("%H:%M:%S")
        lbl._history.insert(0, f"[{now_str}] {msg}")
        if len(lbl._history) > 3:
            lbl._history.pop()
            
        base = getattr(lbl, '_base_tooltip', lbl.toolTip())
        lbl.setToolTip(f"{base}\n\nRecent Activity:\n" + "\n".join(lbl._history))

    def update_utc_clock(self):
        """Updates live UTC clock on top, and dynamic sync age widgets on bottom."""
        now_utc = datetime.now(timezone.utc)
        clock_text = now_utc.strftime("Time: %H:%M UTC")
        if hasattr(self, "lbl_utc_clock_top"):
            self.lbl_utc_clock_top.setText(clock_text)

        now = time.time()

        def format_age(last_time: float, expected_interval: int) -> tuple[str, str]:
            if last_time == 0:
                return "<1m", "#7ee787"  # Green
            
            elapsed = int(now - last_time)
            
            if elapsed > expected_interval * 3:
                color = "#f85149" # Red
            elif elapsed > expected_interval * 1.5:
                color = "#d29922" # Yellow
            else:
                color = "#7ee787" # Green
                
            if elapsed < 60:
                text = "<1m"
            else:
                text = f"{elapsed // 60}m"
                
            return text, color

        if hasattr(self, "lbl_status_pota"):
            pota_interval = 60 # POTA updates frequently (1-5m based on user dropdown)
            idx = getattr(self, 'refresh_interval_idx', 2) # Default 1m
            if idx == 0: pota_interval = 999999
            elif idx == 1: pota_interval = 30
            elif idx == 2: pota_interval = 60
            elif idx == 3: pota_interval = 180
            elif idx == 4: pota_interval = 300
            
            text, color = format_age(self.last_pota_fetch_time, pota_interval)
            self.lbl_status_pota.setText(f"POTA: {text}")
            self.lbl_status_pota.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

        if hasattr(self, "lbl_status_pskr"):
            # PSK updates via round robin every 1-15 minutes
            interval = max(60, 900 // max(1, len(getattr(self, 'rbn_nodes_list', ["W1AW"]))))
            text, color = format_age(self.last_psk_fetch_time, interval)
            self.lbl_status_pskr.setText(f"PSKR/RBN: {text}")
            self.lbl_status_pskr.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

        if hasattr(self, "lbl_status_swpc"):
            text, color = format_age(self.last_swpc_fetch_time, 1200) # 20m
            self.lbl_status_swpc.setText(f"SWPC: {text}")
            self.lbl_status_swpc.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

        if hasattr(self, "lbl_status_drap"):
            drap_time = get_drap_last_sync_time()
            if getattr(self, '_last_drap_time_tracked', 0) != drap_time and drap_time > 0:
                self._last_drap_time_tracked = drap_time
                self.update_widget_history(self.lbl_status_drap, "Fetched updated HAF grid")
                
            text, color = format_age(drap_time, 900) # 15m
            if get_drap_status().startswith("Error"):
                text = "Error"
                color = "#f85149"
            self.lbl_status_drap.setText(f"DRAP: {text}")
            self.lbl_status_drap.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

        if hasattr(self, "lbl_status_wx"):
            text, color = format_age(self.last_wx_fetch_time, 900) # 15m
            self.lbl_status_wx.setText(f"WX: {text}")
            self.lbl_status_wx.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

        if hasattr(self, "lbl_status_ltng"):
            text, color = format_age(self.last_ltng_fetch_time, 5) # 5s
            self.lbl_status_ltng.setText(f"LTNG: {text}")
            self.lbl_status_ltng.setStyleSheet(f"color: {color}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")

    def get_worked_status(self, park_ref: str) -> Optional[str]:
        """
        Evaluates whether a park was worked today vs on a previous UTC day.
        Returns:
            "TODAY" - Worked today (current UTC day) -> [WORKED]
            "PREVIOUS_DAY" - Worked on a previous UTC day (before 00Z) -> Hunted(W)
            None - Not manually worked
        """
        if not park_ref:
            return None
        ref = normalize_ref(park_ref)
        if not ref or ref not in self.manually_worked_parks:
            return None

        worked_date = str(self.manually_worked_parks.get(ref, "")).strip()
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if worked_date == today_utc:
            return "TODAY"
        elif worked_date and worked_date < today_utc:
            return "PREVIOUS_DAY"
        else:
            return "TODAY"

    def check_utc_day_rollover(self):
        """Monitors 00Z UTC day transitions while app is running, transitioning worked spots to Hunted(W)."""
        current_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if hasattr(self, "_last_evaluated_utc_date") and self._last_evaluated_utc_date != current_utc:
            self._last_evaluated_utc_date = current_utc
            self.recompute_comparisons()
        else:
            self._last_evaluated_utc_date = current_utc

    def init_ui(self):
        self.setStyleSheet(DARK_STYLESHEET)
        self.create_menu_bar()

        # Status Bar (initialize early so signal callbacks during UI creation can post messages)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        def make_status_lbl(tooltip=""):
            lbl = QLabel()
            lbl.setStyleSheet(
                "color: #8b949e; font-family: 'Consolas', 'Courier New', monospace; "
                "font-weight: bold; font-size: 13px; background-color: #161b22; "
                "border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;"
            )
            lbl._base_tooltip = tooltip
            lbl._history = []
            lbl.setToolTip(tooltip)
            self.status_bar.addPermanentWidget(lbl)
            return lbl

        self.lbl_status_pota = make_status_lbl("POTA API Spots Sync Status")
        self.lbl_status_pskr = make_status_lbl("PSKReporter / RBN Nodes Sync Status")
        self.lbl_status_swpc = make_status_lbl("NOAA SWPC Solar Weather Sync Status")
        self.lbl_status_drap = make_status_lbl("NOAA SWPC D-RAP Absorption Model Sync Status")
        self.lbl_status_wx = make_status_lbl("NWS Regional Weather Sync Status")
        self.lbl_status_ltng = make_status_lbl("Blitzortung Regional Lightning Sync Status")
        self.lbl_status_map = make_status_lbl("Maps: Gathering data...")
        self.lbl_status_map.setText("Maps: Gathering data...")

        self.heatmap_cache_service = HeatmapCacheService(self)
        self.heatmap_cache_service.status_updated.connect(lambda txt, tt, col: (
            self.lbl_status_map.setText(txt),
            self.lbl_status_map.setToolTip(tt),
            self.lbl_status_map.setStyleSheet(f"color: {col}; font-family: 'Consolas', monospace; font-weight: bold; font-size: 13px; background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; padding: 3px 12px; margin-right: 4px;")
        ))
        self.heatmap_cache_service.cache_ready.connect(self.on_heatmap_cache_ready)
        self.heatmap_cache_service.start()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(6)

        # 1. Header & Source Selector Bar
        top_bar = self.create_top_bar()
        main_layout.addWidget(top_bar)

        # 2. Stat Cards Dashboard
        stats_bar = self.create_stats_bar()
        main_layout.addWidget(stats_bar)

        # 3. Filter Controls Box
        filter_box = self.create_filter_box()
        main_layout.addWidget(filter_box)

        # 4. Main Results Table
        self.table = self.create_table()
        main_layout.addWidget(self.table, stretch=1)

        # 5. Detail & Action Footer Bar
        footer_bar = self.create_footer_bar()
        main_layout.addWidget(footer_bar)

    def handle_browser_filter_changed(self, band, mode, show_grayline):
        self.on_web_grayline_changed(show_grayline)
        self.on_web_filter_changed(band, mode)

    def on_web_filter_changed(self, band, mode):
        self.map_band = band
        self.map_mode = mode
        if self.map_server:
            self.map_server.update_data("band", band)
            self.map_server.update_data("mode", mode)
        self.recalculate_map_heatmap(band, mode)

    def on_web_grayline_changed(self, show_grayline):
        pass  # Grayline coordinates are now pushed periodically by push_all_data_to_map, client toggles visibility locally.

    def show_map_window(self):
        active_band = getattr(self, 'map_band', '20m')
        active_mode = getattr(self, 'map_mode', 'SSB')
        if active_band in ("All", "All Bands", "Other"):
            active_band = "20m"
            self.map_band = "20m"
        if active_mode in ("All", "All Modes"):
            active_mode = "SSB"
            self.map_mode = "SSB"
            
        if self.map_server:
            self.map_server.update_data("band", active_band)
            self.map_server.update_data("mode", active_mode)

        use_browser = False
        if getattr(self, 'map_render_mode', MAP_RENDER_AUTO) == MAP_RENDER_BROWSER:
            use_browser = True
        elif getattr(self, 'map_render_mode', MAP_RENDER_AUTO) == MAP_RENDER_AUTO and self.is_chromebook:
            use_browser = True

        if use_browser:
            self.push_all_data_to_map()
            if self.map_server:
                open_map_browser(self.map_server.get_url())
            if not self.map_timer.isActive():
                self.map_timer.start()
            return

        try:
            if not self.map_window:
                self.map_window = MapWindow(self)
            else:
                self.map_window.set_filter_state(active_band, active_mode)
            
            self.map_window.show()
            self.map_window.raise_()
            self.map_window.activateWindow()
            
            self.push_all_data_to_map()
            
            if not self.map_timer.isActive():
                self.map_timer.start()
        except Exception as e:
            logging.warning(f"Native Qt MapWindow failed to initialize ({e}). Falling back to browser server.")
            self.push_all_data_to_map()
            if self.map_server:
                open_map_browser(self.map_server.get_url())
            if not self.map_timer.isActive():
                self.map_timer.start()

    def update_map_spots_only(self):
        """Pushes latest spot pins and band counts to the map without recalculating 10-minute propagation heatmap."""
        if not self.map_window and not self.map_server:
            return
            
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)

        # Push spots
        map_spots = []
        for c in self.compared_spots:
            if c.propagation and c.spot.latitude is not None and c.spot.longitude is not None:
                if getattr(c.propagation, 'ray_mode', '') == 'QRT' or (c.propagation.spot_evidence and c.propagation.spot_evidence.is_qrt):
                    continue
                has_plus = c.has_local_evidence
                is_worked = (not c.is_new) or (self.get_worked_status(c.spot.reference) is not None)
                is_qrp = bool(c.spot_evidence and getattr(c.spot_evidence, "is_qrp", False))
                qrp_desc = str(getattr(c.spot_evidence, "qrp_desc", "")) if (c.spot_evidence and is_qrp) else ""
                map_spots.append({
                    "lat": c.spot.latitude,
                    "lon": c.spot.longitude,
                    "score": c.propagation.probability_pct,
                    "has_plus": has_plus,
                    "is_worked": is_worked,
                    "is_qrp": is_qrp,
                    "qrp_desc": qrp_desc,
                    "call": c.spot.activator,
                    "park": f"{c.spot.reference} ({c.spot.park_name})" if c.spot.park_name else c.spot.reference,
                    "band": c.spot.band,
                    "freq": c.frequency_mhz_str,
                    "mode": getattr(c.spot, "mode", "SSB"),
                    "muf": round(c.propagation.muf_est_mhz, 1) if getattr(c.propagation, 'muf_est_mhz', None) else None
                })
        if self.map_window:
            self.map_window.update_spots(map_spots)
        if self.map_server:
            if home_lat is not None and home_lon is not None:
                self.map_server.update_data("home_lat", home_lat)
                self.map_server.update_data("home_lon", home_lon)
            self.map_server.update_data("spots", map_spots)
        
        # Band counts
        band_parks = {}
        for spot in map_spots:
            band = spot["band"]
            park = spot["park"]
            if band not in band_parks:
                band_parks[band] = set()
            band_parks[band].add(park)
        band_counts = {band: len(parks) for band, parks in band_parks.items()}
        band_counts["All"] = len(set(spot["park"] for spot in map_spots))
        if self.map_window:
            self.map_window.update_band_counts(band_counts)
        if self.map_server:
            self.map_server.update_data("band_counts", band_counts)
            
        # Re-apply Gaussian spot blending to the currently viewed map immediately!
        active_band = getattr(self, 'map_band', '20m')
        active_mode = getattr(self, 'map_mode', 'SSB')
        if active_band not in ("All", "All Bands", "Other"):
            self.recalculate_map_heatmap(active_band, active_mode)

    def push_all_data_to_map(self):
        """Pushes full map state (spots, grayline, lightning, and recomputes 10-minute propagation heatmap)."""
        if not self.map_window and not self.map_server:
            return
            
        self.update_map_spots_only()
        
        # Grayline
        lines = []
        def add_line(z, style):
            p = calculate_grayline_polylines(z)
            lines.append({"coords": p, "style": style})
        add_line(90.0, {"color": "black", "weight": 2, "dashArray": ""})
        add_line(96.0, {"color": "black", "weight": 1, "dashArray": "5, 5"})
        add_line(84.0, {"color": "#777777", "weight": 1, "dashArray": "5, 5"})
        if self.map_window:
            self.map_window.update_grayline(lines)
        if self.map_server:
            self.map_server.update_data("grayline", lines)

        # Aurora Oval
        if getattr(self, "aurora_lines", None):
            if self.map_window:
                self.map_window.update_aurora(self.aurora_lines)
            if self.map_server:
                self.map_server.update_data("aurora", self.aurora_lines)
        elif time.time() - getattr(self, "last_aurora_fetch_time", 0.0) > 900.0:
            self.fetch_aurora()
        
        # Lightning
        if getattr(self, 'lightning_summary', None):
            self.update_map_lightning(self.lightning_summary)
            
        # Heatmap calculation is now seamlessly triggered by update_map_spots_only() above

    def on_map_timer_tick(self):
        if (self.map_window and self.map_window.isVisible()) or self.map_server:
            self.push_all_data_to_map()

    def recalculate_map_heatmap(self, band: str, mode: str = "SSB"):
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime("%H:%M")
        
        if band in ("All", "All Bands", "Other") or (not self.map_window and not self.map_server):
            if self.map_window:
                self.map_window.update_heatmap("[]")
                self.map_window.set_last_update(now_str)
            if self.map_server:
                self.map_server.update_data("heatmap", "[]")
                self.map_server.update_data("last_update", now_str)
            return
            
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if not home_lat or not home_lon:
            return

        live_spots = []
        for c in self.compared_spots:
            if c.spot.band and c.spot.band.lower() == band.lower() and c.propagation and c.spot.latitude is not None and c.spot.longitude is not None:
                if getattr(c.propagation, 'ray_mode', '') == 'QRT' or (c.propagation.spot_evidence and c.propagation.spot_evidence.is_qrt):
                    continue
                    
                spot_mode = getattr(c.spot, "mode", "SSB").upper()
                mode_matches = False
                if mode == "SSB" and spot_mode in ("SSB", "FM", "AM"): mode_matches = True
                elif mode == "CW" and spot_mode == "CW": mode_matches = True
                elif mode == "FT8" and spot_mode == "FT8": mode_matches = True
                elif mode == "FT4" and spot_mode == "FT4": mode_matches = True
                elif mode == "DATA" and spot_mode not in ("SSB", "FM", "AM", "CW"): mode_matches = True
                
                if mode_matches:
                    live_spots.append({
                        "lat": float(c.spot.latitude),
                        "lon": float(c.spot.longitude),
                        "score": float(c.propagation.probability_pct)
                    })

        cached_json = self.heatmap_cache_service.heatmap_cache.get((band, mode))
        if cached_json:
            blend_worker = GaussianBlendWorker(band, mode, cached_json, live_spots)
            blend_worker.signals.finished.connect(self.on_map_heatmap_calculated)
            self._run_worker(blend_worker)
            return

        worker = MapPropagationWorker(
            home_lat=home_lat,
            home_lon=home_lon,
            home_grid=self.current_grid,
            band=band,
            mode=mode,
            solar_weather=getattr(self, 'solar_weather', None) or SolarWeather(),
            tx_power=self.tx_power,
            antenna_type=self.antenna_type,
            lightning=getattr(self, 'lightning_summary', None),
            regional_matrix=getattr(self, 'regional_matrix', None),
            live_spots=live_spots
        )
        worker.signals.finished.connect(self.on_map_heatmap_calculated)
        
        if self.map_window:
            self.map_window.set_last_update("Updating... Standby...")
        if self.map_server:
            self.map_server.update_data("last_update", "Updating... Standby...")
            
        self._run_worker(worker)

    @pyqtSlot(str, str, str)
    def on_heatmap_cache_ready(self, band: str, mode: str, json_data: str):
        if not self.btn_map.isEnabled():
            self.btn_map.setText("Live Map")
            self.btn_map.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
            self.btn_map.setEnabled(True)
            
        # Push the cache status to the map so it can color-code the dropdown
        cache_status = {}
        for b in self.heatmap_cache_service.bands_to_cache:
            cache_status[b] = (b, "SSB") in self.heatmap_cache_service.heatmap_cache
        if self.map_server:
            self.map_server.update_data("cache_status", cache_status)
        if self.map_window:
            self.map_window.update_cache_status(cache_status)
            
        # If the map is currently viewing this band/mode, update it immediately!
        if self.map_band == band and self.map_mode == mode:
            self.on_map_heatmap_calculated(band, mode, json_data)

    @pyqtSlot(str, str, str)
    def on_map_heatmap_calculated(self, band: str, mode: str, heatmap_json: str):
        if heatmap_json and heatmap_json != "[]":
            self._has_initial_heatmap = True
            
        from datetime import datetime, timezone
        last_update = datetime.now(timezone.utc).strftime("%H:%M")
        if self.map_window:
            self.map_window.update_heatmap(heatmap_json)
            self.map_window.set_last_update(last_update)
        if self.map_server:
            self.map_server.update_data("heatmap", heatmap_json)
            self.map_server.update_data("last_update", last_update)
            
    def update_map_lightning(self, summary):
        cells = []
        if summary and hasattr(summary, 'storm_cells') and summary.storm_cells:
            for c in summary.storm_cells:
                if c.latitude is not None and c.longitude is not None:
                    cells.append({
                        "lat": float(c.latitude),
                        "lon": float(c.longitude),
                        "heading": float(c.movement_heading_deg) if c.movement_heading_deg is not None else None,
                        "speed": float(c.movement_speed_mph) if c.movement_speed_mph is not None else None,
                        "strikes": int(getattr(c, 'total_strikes_in_cluster', 0) or getattr(c, 'estimated_strikes_15m', 0) or getattr(c, 'actual_strikes_in_polygon', 0) or 0),
                        "event_type": str(getattr(c, 'event_type', 'Thunderstorm')),
                        "headline": str(getattr(c, 'headline', ''))
                    })
        if self.map_window:
            self.map_window.update_lightning(cells)
        if self.map_server:
            self.map_server.update_data("lightning", cells)

    def show_settings_dialog(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            new_call = dlg.txt_call.text().strip().upper()
            new_grid = dlg.txt_grid.text().strip().upper()
            new_rbn = dlg.txt_rbn.text().strip().upper()
            new_p2p_mode = dlg.chk_start_p2p.isChecked()
            new_p2p_park = dlg.txt_p2p_park.text().strip().upper()
            new_map_mode = dlg.combo_map_mode.currentData() or MAP_RENDER_AUTO
            new_low_mem = dlg.chk_low_mem.isChecked()
            
            settings = QSettings("POTA", "HunterComparator")
            settings.setValue("p2p_mode", new_p2p_mode)
            settings.setValue("p2p_my_park", new_p2p_park)
            settings.setValue("map_render_mode", new_map_mode)
            settings.setValue("low_memory_mode", new_low_mem)
            self.map_render_mode = new_map_mode
            self.low_memory_mode = new_low_mem
            
            if new_call != self.my_call:
                self.my_call = new_call
                self.txt_my_call.setText(new_call)
                self.on_my_call_changed()
                
            self.p2p_mode = new_p2p_mode
            self.p2p_my_park = new_p2p_park
            self.chk_p2p.setChecked(new_p2p_mode)
            self.txt_p2p_park.setText(new_p2p_park)
            
            if new_p2p_mode:
                self.current_grid = new_grid
                self.txt_grid.setText(new_grid)
                self.on_p2p_park_changed()
            else:
                self.home_grid = new_grid
                self.current_grid = new_grid
                self.txt_grid.setText(new_grid)
                self.on_grid_changed()
                
            if new_rbn != getattr(self, 'rbn_nodes_str', ''):
                self.rbn_nodes_str = new_rbn
                settings.setValue("rbn_nodes_str", new_rbn)
                # Parse list and restart timer
                self.rbn_nodes_list = [c.strip().upper() for c in new_rbn.split(',') if c.strip()]
                self._current_psk_node_idx = 0
                self.fetch_psk_spots()

    def create_menu_bar(self):
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")

        reload_csv_action = QAction("&Reload Hunter Log CSV...", self)
        reload_csv_action.setShortcut(QKeySequence("Ctrl+O"))
        reload_csv_action.triggered.connect(self.browse_csv_file)
        file_menu.addAction(reload_csv_action)

        export_action = QAction("&Export Table View to CSV...", self)
        export_action.setShortcut(QKeySequence("Ctrl+S"))
        export_action.triggered.connect(self.export_table_csv)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        settings_action = QAction("&Preferences...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+P"))
        settings_action.triggered.connect(self.show_settings_dialog)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View / Layout Menu
        view_menu = menu_bar.addMenu("&View")

        refresh_action = QAction("&Refresh Active Spots Now", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.fetch_spots)
        view_menu.addAction(refresh_action)

        map_action = QAction("Live &Propagation && Weather Map", self)
        map_action.setShortcut(QKeySequence("F4"))
        map_action.triggered.connect(self.show_map_window)
        view_menu.addAction(map_action)

        view_menu.addSeparator()

        autofit_action = QAction("Auto-fit Column Widths", self)
        autofit_action.triggered.connect(self.autofit_columns)
        view_menu.addAction(autofit_action)

        reset_cols_action = QAction("Reset Column Layout to Default", self)
        reset_cols_action.triggered.connect(self.reset_column_widths)
        view_menu.addAction(reset_cols_action)

        view_menu.addSeparator()

        noise_matrix_action = QAction("Receiver Band &Noise Floor Matrix (ITU-R P.372)", self)
        noise_matrix_action.setShortcut(QKeySequence("F6"))
        noise_matrix_action.triggered.connect(self.show_band_noise_dialog)
        view_menu.addAction(noise_matrix_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction("&About POTA Prop", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        docs_action = QAction("&Documentation", self)
        docs_action.setShortcut(QKeySequence("F2"))
        docs_action.triggered.connect(self.show_docs_dialog)
        help_menu.addAction(docs_action)

        help_menu.addSeparator()

        pota_web_action = QAction("Visit POTA.app Website", self)
        pota_web_action.triggered.connect(lambda: webbrowser.open("https://pota.app"))
        help_menu.addAction(pota_web_action)

        help_menu.addSeparator()

        donate_action = QAction("Donate", self)
        donate_action.triggered.connect(self.show_donate_dialog)
        help_menu.addAction(donate_action)


    def autofit_columns(self):
        if hasattr(self, 'table') and self.table:
            self.table.resizeColumnsToContents()

    def show_docs_dialog(self):
        dlg = DocumentationDialog(self)
        dlg.exec()

    def show_donate_dialog(self):
        dlg = DonateDialog(self)
        dlg.exec()

    def show_about_dialog(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def show_band_noise_dialog(self):
        h_lat, h_lon = maidenhead_to_latlon(self.current_grid)
        if h_lat is None or h_lon is None:
            h_lat, h_lon = 37.0, -95.0
        dlg = BandNoiseDialog(
            home_lat=h_lat,
            home_lon=h_lon,
            solar_weather=self.solar_weather,
            lightning_summary=self.lightning_summary,
            parent=self,
        )
        dlg.exec()

    def _format_noise_tooltip_html(self, matrix: List[BandNoiseBreakdown]) -> str:
        lines = [
            "<div style='font-family: sans-serif; font-size: 11px; color: #e6edf3;'>",
            "<b style='color: #58a6ff; font-size: 12px;'>Real-Time Receiver Noise Floor Matrix</b><br/>",
            "<span style='color: #8b949e;'>ITU-R P.372 Diurnal Baseline &amp; Blitzortung QRN</span><br/><br/>",
            "<table style='border-collapse: collapse; width: 100%; text-align: right;'>",
            "<tr style='color: #8b949e; border-bottom: 1px solid #30363d; font-weight: bold;'>",
            "<th style='text-align: left; padding: 2px 6px;'>Band</th>",
            "<th style='padding: 2px 6px;'>Atmosphere</th>",
            "<th style='padding: 2px 6px;'>Space</th>",
            "<th style='padding: 2px 6px;'>Total Fa</th>",
            "<th style='padding: 2px 6px;'>Est. S-Meter</th>",
            "</tr>",
        ]
        for b in matrix:
            if b.s_units_val >= 8.0:
                s_col = "#f85149"
            elif b.s_units_val >= 4.0:
                s_col = "#ffa657"
            elif b.s_units_val >= 2.0:
                s_col = "#f1e05a"
            else:
                s_col = "#7ee787"

            qrn_extra = f" (+{b.qrn_surge_db:.0f}dB)" if b.qrn_surge_db >= 1.0 else ""
            lines.append(
                f"<tr style='border-bottom: 1px solid #21262d;'>"
                f"<td style='text-align: left; font-weight: bold; color: #58a6ff; padding: 2px 6px;'>{b.band}</td>"
                f"<td style='color: #c9d1d9; padding: 2px 6px;'>{b.f_atm_total_db:.1f} dB{qrn_extra}</td>"
                f"<td style='color: #bc8cff; padding: 2px 6px;'>{b.f_gal_db:.1f} dB</td>"
                f"<td style='font-weight: bold; color: #e6edf3; padding: 2px 6px;'>{b.f_a_total_db:.1f} dB</td>"
                f"<td style='font-weight: bold; color: {s_col}; padding: 2px 6px;'>{b.s_units_label}</td>"
                f"</tr>"
            )
        lines.append("</table><br/>")
        lines.append("<span style='color: #7ee787;'>Click card to open full Noise Matrix window (or press F6)</span>")
        lines.append("</div>")
        return "".join(lines)


    def create_top_bar(self) -> QWidget:

        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # App Title
        lbl_app = QLabel("POTA Prop")
        lbl_app.setStyleSheet("color: #f0f6fc; font-size: 16px; font-weight: bold;")
        layout.addWidget(lbl_app)

        # Top Bar UTC Clock Badge
        self.lbl_utc_clock_top = QLabel()
        self.lbl_utc_clock_top.setStyleSheet(
            "color: #79c0ff; font-family: 'Consolas', 'Courier New', monospace; "
            "font-weight: bold; font-size: 13px; background-color: #161b22; "
            "border: 1px solid #30363d; border-radius: 4px; padding: 3px 10px;"
        )
        self.lbl_utc_clock_top.setToolTip("Current Coordinated Universal Time (UTC)")
        layout.addWidget(self.lbl_utc_clock_top)

        layout.addSpacing(6)

        # Operator Callsign Input (Hidden, moved to Settings)
        self.txt_my_call = QLineEdit(self.my_call)
        self.txt_my_call.returnPressed.connect(self.on_my_call_changed)
        self.txt_my_call.editingFinished.connect(self.on_my_call_changed)
        self.txt_my_call.hide()

        # Single Unified Grid Locator Input (Hidden, moved to Settings)
        self.txt_grid = QLineEdit(self.current_grid)
        self.txt_grid.returnPressed.connect(self.on_grid_changed)
        self.txt_grid.editingFinished.connect(self.on_grid_changed)
        self.txt_grid.hide()

        # P2P Mode Controls
        self.chk_p2p = QCheckBox("P2P Mode")
        self.chk_p2p.setChecked(self.p2p_mode)
        self.chk_p2p.setStyleSheet("color: #bc8cff; font-weight: bold;")
        self.chk_p2p.setToolTip("Toggle Park-to-Park (P2P) mode when operating portable from a park")
        self.chk_p2p.toggled.connect(self.on_p2p_toggled)
        layout.addWidget(self.chk_p2p)

        self.lbl_p2p_park = QLabel("Park:")
        self.lbl_p2p_park.setStyleSheet("color: #bc8cff; font-weight: 600;")
        layout.addWidget(self.lbl_p2p_park)

        self.txt_p2p_park = QLineEdit(self.p2p_my_park)
        self.txt_p2p_park.setPlaceholderText("e.g. US-1234")
        self.txt_p2p_park.setMaxLength(12)
        self.txt_p2p_park.setFixedWidth(80)
        self.txt_p2p_park.setToolTip("Your field park reference (e.g. US-1234) — Grid will auto-update to park location!")
        self.txt_p2p_park.returnPressed.connect(self.on_p2p_park_changed)
        self.txt_p2p_park.editingFinished.connect(self.on_p2p_park_changed)
        layout.addWidget(self.txt_p2p_park)

        self.update_p2p_ui_visibility()

        layout.addSpacing(6)

        # POTA Log File Selector (Button with active path hover tooltip)
        self.txt_csv_path = QLineEdit(self.csv_path)  # Maintained for programmatic compatibility
        self.btn_select_csv = QPushButton("Select POTA Log")
        self.btn_select_csv.setToolTip(f"Active Log: {self.csv_path}" if self.csv_path else "Click to select hunter_parks.csv log file")
        self.btn_select_csv.clicked.connect(self.browse_csv_file)
        layout.addWidget(self.btn_select_csv)

        # Sync Log Button
        self.btn_sync_log = QPushButton("Sync Log")
        self.btn_sync_log.setToolTip("Download and sync latest hunted parks from POTA API")
        self.btn_sync_log.clicked.connect(self.sync_hunter_log)
        self.btn_sync_log.setEnabled(False) # Will be enabled if logged in
        layout.addWidget(self.btn_sync_log)

        # Auth Button
        self.btn_auth = QPushButton("Sign In POTA.app")
        self.btn_auth.setToolTip("Sign in via AWS Cognito to enable auto-sync and spotting")
        self.btn_auth.clicked.connect(self.on_auth_clicked)
        layout.addWidget(self.btn_auth)

        # Initialize UI auth state
        self.on_auth_state_changed(self.authenticator.is_logged_in())

        layout.addStretch()

        # Auto refresh selector
        lbl_auto = QLabel("Auto-Refresh:")
        lbl_auto.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(lbl_auto)

        self.combo_refresh = QComboBox()
        self.combo_refresh.addItems(
            ["Manual Only", "Every 30 sec", "Every 1 min", "Every 2 min", "Every 5 min"]
        )
        self.combo_refresh.currentIndexChanged.connect(self.on_refresh_interval_changed)
        if 0 <= self.refresh_interval_idx < self.combo_refresh.count():
            self.combo_refresh.setCurrentIndex(self.refresh_interval_idx)
        else:
            self.combo_refresh.setCurrentIndex(2)  # Default 1 min
        layout.addWidget(self.combo_refresh)

        # Fetch Spots Button
        self.btn_fetch = QPushButton("Fetch Spots")
        self.btn_fetch.setObjectName("btnPrimary")
        self.btn_fetch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fetch.clicked.connect(self.fetch_spots)
        layout.addWidget(self.btn_fetch)

        return panel

    def create_stats_bar(self) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.card_new = StatCard("New", "0", "#f1e05a")
        self.card_hunted = StatCard("Hunted", "0", "#2ea043")
        self.card_active = StatCard("Spots", "0", "#58a6ff")
        self.card_unique_parks = StatCard("Active Parks", "0", "#bc8cff")
        self.card_total_hunted = StatCard("Total in Log", "0", "#8b949e")
        self.card_solar = StatCard("Space Weather", "SSN: -- | SFI: -- | A: -- | K: -- | Flare: --", "#388bfd")
        self.card_solar.setToolTip(self.solar_weather.format_tooltip_html())
        self.card_meteor = StatCard("Meteor Activity", "ZHR: -- | Shower: --", "#8b949e")
        self.card_lightning = StatCard("Lightning", "1", "#2ea043")
        self.card_noise = StatCard("Noise", "40m: S0 | 20m: S0", "#58a6ff", is_clickable=True)
        self.card_noise.clicked.connect(self.show_band_noise_dialog)
        self.card_weather = StatCard("Weather", "--°F", "#58a6ff")

        layout.addWidget(self.card_new, stretch=1)
        layout.addWidget(self.card_hunted, stretch=1)
        layout.addWidget(self.card_active, stretch=1)
        layout.addWidget(self.card_unique_parks, stretch=1)
        layout.addWidget(self.card_total_hunted, stretch=1)
        layout.addWidget(self.card_solar, stretch=13)
        layout.addWidget(self.card_meteor, stretch=6)
        layout.addWidget(self.card_lightning, stretch=2)
        layout.addWidget(self.card_noise, stretch=4)
        layout.addWidget(self.card_weather, stretch=5)

        return panel

    def create_filter_box(self) -> QGroupBox:
        box = QGroupBox("Filter & Search Active Spots")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # 1. Status Filter (All, New Only, Hunted Only, P2P Only)
        lbl_status = QLabel("Status:")
        lbl_status.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_status)

        self.combo_status = QComboBox()
        self.combo_status.addItems([
            "All",
            "New",
            "Hunted",
            "Worked",
            "P2P",
        ])
        if 0 <= self.filter_status_idx < self.combo_status.count():
            self.combo_status.setCurrentIndex(self.filter_status_idx)
        self.combo_status.currentIndexChanged.connect(self.apply_filters)
        layout.addWidget(self.combo_status)

        # 2. Score Filter
        lbl_dx = QLabel("Score:")
        lbl_dx.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_dx)

        self.combo_dx = QComboBox()
        self.combo_dx.addItems(
            ["All", ">= 25", ">= 50", ">= 75", ">= 99"]
        )
        if 0 <= self.filter_dx_idx < self.combo_dx.count():
            self.combo_dx.setCurrentIndex(self.filter_dx_idx)
        self.combo_dx.setToolTip("Filter spots by RF propagation score from your QTH (higher = better path)")
        self.combo_dx.currentIndexChanged.connect(self.apply_filters)
        layout.addWidget(self.combo_dx)

        # 3. Band Filter
        lbl_band = QLabel("Band:")
        lbl_band.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_band)

        self.combo_band = QComboBox()
        self.combo_band.addItems(
            [
                "All",
                "160m",
                "80m",
                "60m",
                "40m",
                "30m",
                "20m",
                "17m",
                "15m",
                "12m",
                "10m",
                "6m",
                "2m",
                "70cm",
                "Other",
            ]
        )
        band_idx = self.combo_band.findText(self.filter_band)
        if band_idx >= 0:
            self.combo_band.setCurrentIndex(band_idx)
        self.combo_band.currentIndexChanged.connect(self.apply_filters)
        layout.addWidget(self.combo_band)

        # 4. Mode Filter
        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(
            [
                "All",
                "CW",
                "SSB",
                "FT8",
                "DATA",
                "FM",
                "AM",
            ]
        )
        mode_idx = self.combo_mode.findText(self.filter_mode)
        if mode_idx >= 0:
            self.combo_mode.setCurrentIndex(mode_idx)
        elif self.filter_mode in ("All Modes", ""):
            self.combo_mode.setCurrentIndex(0)
        self.combo_mode.currentIndexChanged.connect(self.apply_filters)
        layout.addWidget(self.combo_mode)

        # 5. Station Power Output
        lbl_power = QLabel("Power:")
        lbl_power.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_power)

        self.combo_power = QComboBox()
        pwr_idx_to_select = 4  # Default 100W
        for idx, (p_label, p_val) in enumerate(POWER_PRESETS):
            self.combo_power.addItem(p_label, p_val)
            if abs(p_val - self.tx_power) < 0.1:
                pwr_idx_to_select = idx
        self.combo_power.setCurrentIndex(pwr_idx_to_select)
        self.combo_power.setToolTip("Transmitter output power in Watts (used for RF link budget and QSO Score calculations)")

        self.combo_power.currentIndexChanged.connect(self.on_station_config_changed)
        layout.addWidget(self.combo_power)

        # 6. Station Antenna Type
        lbl_antenna = QLabel("Antenna:")
        lbl_antenna.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_antenna)

        self.combo_antenna = QComboBox()
        ant_idx_to_select = 0
        for idx, (a_key, a_conf) in enumerate(ANTENNA_PRESETS.items()):
            self.combo_antenna.addItem(a_conf["name"], a_key)
            if a_key.upper() == self.antenna_type.upper() or a_conf["name"] == self.antenna_type:
                ant_idx_to_select = idx
        self.combo_antenna.setCurrentIndex(ant_idx_to_select)
        self.combo_antenna.setToolTip("Operating antenna type (gain and elevation radiation characteristics)")
        self.combo_antenna.currentIndexChanged.connect(self.on_station_config_changed)
        layout.addWidget(self.combo_antenna)

        # 7. Search Filter
        lbl_search = QLabel("Search:")
        lbl_search.setStyleSheet("color: #8b949e; font-weight: bold;")
        layout.addWidget(lbl_search)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search Park ID, Name, Activator, State...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.apply_filters)
        layout.addWidget(self.txt_search, stretch=2)

        # 8. Tooltip Mouseover Toggle Checkbox
        self.chk_tooltips = QCheckBox("Tooltips")
        self.chk_tooltips.setChecked(self.show_tooltips)
        self.chk_tooltips.setToolTip(
            "Toggle row mouseover popups showing nearby re-spots and QSO success intel"
        )
        self.chk_tooltips.toggled.connect(self.on_tooltips_toggled)
        layout.addWidget(self.chk_tooltips)

        # Reset button
        btn_reset = QPushButton("Clear Filters")
        btn_reset.clicked.connect(self.reset_filters)
        layout.addWidget(btn_reset)

        # Live Map button
        self.btn_map = QPushButton("Getting Data...")
        self.btn_map.setStyleSheet("background-color: gray; color: white; font-weight: bold;")
        self.btn_map.setEnabled(False)
        self.btn_map.setToolTip("Open interactive Live Propagation, Space Weather & Doppler Radar Map (F4)")
        self.btn_map.clicked.connect(self.show_map_window)
        layout.addWidget(self.btn_map)

        return box

    @pyqtSlot(bool)
    def on_auth_state_changed(self, logged_in: bool):
        if logged_in:
            callsign = self.authenticator.get_callsign() or self.authenticator.get_username()
            btn_text = f"Sign Out ({callsign})" if callsign else "Sign Out"
            self.btn_auth.setText(btn_text)
            self.btn_auth.setStyleSheet("background-color: #238636; color: #ffffff;")
            self.btn_sync_log.setEnabled(True)

            # Automatically populate operator callsign and home grid in preferences
            if callsign:
                clean_call = callsign.strip().upper()
                self.set_operator_callsign(clean_call)
                self.status_bar.showMessage(f"Signed in as {clean_call}. Location and grid updated in Preferences.", 5000)
            else:
                self.status_bar.showMessage("Successfully signed in to POTA.", 5000)

            # Auto-sync on login
            self.sync_hunter_log()
        else:
            self.btn_auth.setText("Sign In POTA.app")
            self.btn_auth.setStyleSheet("")
            self.btn_sync_log.setEnabled(False)

    def on_auth_clicked(self):
        if self.authenticator.is_logged_in():
            self.authenticator.logout()
            self.status_bar.showMessage("Signed out.", 3000)
        else:
            self.authenticator.start_login_flow(self)

    def sync_hunter_log(self):
        token = self.authenticator.get_valid_token()
        if not token:
            self.status_bar.showMessage("Error: Not signed in.")
            return
            
        self.btn_sync_log.setEnabled(False)
        self.btn_sync_log.setText("Syncing...")
        
        worker = SyncWorker(token, self.csv_path)
        worker.signals.finished.connect(self._on_sync_finished)
        worker.signals.error.connect(self._on_sync_error)
        self.threadpool.start(worker)

    @pyqtSlot(dict)
    def _on_sync_finished(self, hunted_map: dict):
        self.btn_sync_log.setEnabled(True)
        self.btn_sync_log.setText("Sync Log")
        
        if hunted_map:
            self.hunted_parks = hunted_map
            self.status_bar.showMessage(f"Sync complete. Found {len(self.hunted_parks)} hunted parks.", 5000)
            self.recompute_comparisons()
        else:
            self.status_bar.showMessage("Sync completed but no parks found or error occurred.", 5000)

    @pyqtSlot(str)
    def _on_sync_error(self, error: str):
        self.btn_sync_log.setEnabled(True)
        self.btn_sync_log.setText("Sync Log")
        self.status_bar.showMessage(f"Sync failed: {error}", 5000)

    def on_table_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        
        item = self.table.itemAt(pos)
        if item is None:
            return
            
        row = item.row()
        
        # Add spot action
        spot_action = menu.addAction("Spot Activator / Re-Spot")
        
        # Execute menu
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == spot_action:
            self.open_spot_dialog(row)

    def open_spot_dialog(self, row: int):
        token = self.authenticator.get_valid_token()
        if not token:
            self.status_bar.showMessage("You must be signed in to submit spots.", 3000)
            
        # Get spot data from table safely
        activator_item = self.table.item(row, 2)
        freq_item = self.table.item(row, 3)
        ref_item = self.table.item(row, 5)
        mode_item = self.table.item(row, 9)
        
        activator = activator_item.text() if activator_item else ""
        freq = freq_item.text() if freq_item else ""
        ref = ref_item.text() if ref_item else ""
        mode = mode_item.text() if mode_item else ""
        
        # Clean up freq if it has MHz
        freq_raw = freq.split(' ')[0]
        try:
            freq_khz = str(float(freq_raw) * 1000)
        except:
            freq_khz = freq_raw
            
        dialog = SpotDialog(activator, ref, freq_khz, mode, self.my_call, self)
        if dialog.exec():
            payload = dialog.get_spot_data()
            mark_worked = dialog.chk_mark_worked.isChecked()
            self.status_bar.showMessage(f"Submitting spot for {payload['activator']}...")
            
            worker = SpotWorker(payload, token)
            
            def on_spot_finished(s):
                self.status_bar.showMessage("Spot submitted successfully!", 5000)
                if mark_worked:
                    self.toggle_park_worked(payload["reference"], force_state=True, activator_call=payload["activator"], skip_prompt=True)
                    
            worker.signals.finished.connect(on_spot_finished)
            worker.signals.error.connect(lambda e: self.status_bar.showMessage(f"Spot failed: {e}", 5000))
            self.threadpool.start(worker)

    def create_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(13)
        table.setHorizontalHeaderLabels(
            [
                "Status",
                "Score",
                "Activator",
                "Frequency",
                "Time",
                "Park ID",
                "Park Name",
                "Location",
                "Band",
                "Mode",
                "Dist / Bearing",
                "Grid",
                "Comments",
            ]
        )

        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self.on_table_context_menu)

        # Make columns interactively adjustable by dragging header boundaries
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)

        # Set default initial column widths
        self.default_column_widths = [105, 80, 95, 110, 80, 95, 230, 130, 65, 70, 130, 75, 200]
        for col, width in enumerate(self.default_column_widths):
            table.setColumnWidth(col, width)


        # Restore previously saved column widths and header state if available
        settings = QSettings("POTA", "HunterComparator")
        saved_header = settings.value("table_header_state")
        if saved_header:
            header.restoreState(saved_header)

        # Header context menu for quick auto-fit and resetting widths
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_context_menu)

        table.itemDoubleClicked.connect(self.on_table_double_clicked)
        table.itemSelectionChanged.connect(self.on_table_selection_changed)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self.show_table_context_menu)

        return table

    def create_footer_bar(self) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.lbl_selection_info = QLabel("Select a park from the table for detailed info.")
        self.lbl_selection_info.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(self.lbl_selection_info, stretch=1)

        self.btn_mark_worked = QPushButton("Mark [WORKED]")
        self.btn_mark_worked.setEnabled(False)
        self.btn_mark_worked.setToolTip("Mark or unmark the selected park as [WORKED]")
        self.btn_mark_worked.clicked.connect(self.toggle_selected_park_worked)
        layout.addWidget(self.btn_mark_worked)

        self.btn_spot_intel = QPushButton("Spot Intelligence")
        self.btn_spot_intel.setEnabled(False)
        self.btn_spot_intel.clicked.connect(self.open_selected_spot_intel)
        layout.addWidget(self.btn_spot_intel)

        self.btn_open_park = QPushButton("Open on POTA.app")
        self.btn_open_park.setObjectName("btnAccent")
        self.btn_open_park.setEnabled(False)
        self.btn_open_park.clicked.connect(self.open_selected_park_web)
        layout.addWidget(self.btn_open_park)

        self.btn_prop_summary = QPushButton("Propagation Summary")
        self.btn_prop_summary.setToolTip("Open comprehensive executive propagation and operating summary")
        self.btn_prop_summary.clicked.connect(self.open_propagation_summary_dialog)
        layout.addWidget(self.btn_prop_summary)

        btn_export = QPushButton("Export Table to CSV")
        btn_export.clicked.connect(self.export_table_csv)
        layout.addWidget(btn_export)

        btn_quit = QPushButton("Quit")
        btn_quit.setObjectName("btnQuit")
        btn_quit.setToolTip("Save all settings and exit (settings are also saved automatically on close)")
        btn_quit.clicked.connect(self.close)
        layout.addWidget(btn_quit)

        return panel

    def load_initial_csv(self):
        if hasattr(self, "txt_csv_path") and self.txt_csv_path.text().strip():
            self.csv_path = self.txt_csv_path.text().strip()
        if hasattr(self, "btn_select_csv"):
            self.btn_select_csv.setToolTip(f"Active Log: {self.csv_path}" if self.csv_path else "Click to select hunter_parks.csv log file")
        if os.path.exists(self.csv_path):
            self.hunted_parks = load_hunter_csv(self.csv_path)
            total_hunted = len(self.hunted_parks)
            total_qsos = sum(p.qsos for p in self.hunted_parks.values())
            self.card_total_hunted.set_value(f"{total_hunted:,}")
            self.status_bar.showMessage(
                f"Loaded {total_hunted:,} hunted parks ({total_qsos:,} QSOs) from {self.csv_path}"
            )
            # Check age of CSV log file (warn in logs if older than 24 hours)
            try:
                mtime = os.path.getmtime(self.csv_path)
                age_seconds = time.time() - mtime
                age_hours = age_seconds / 3600.0
                if age_hours > 24.0:
                    logging.info(f"Local POTA log is {age_hours:.1f} hours old. Consider syncing or reloading.")
            except Exception as e:
                logging.debug("Failed to check CSV file age: %s", e)
        else:
            self.card_total_hunted.set_value("0")
            self.status_bar.showMessage(
                f"No local POTA log loaded. Click 'Select POTA Log' or 'Sign In' to sync your data."
            )

    def browse_csv_file(self):
        start_dir = os.path.dirname(self.csv_path) if os.path.exists(self.csv_path) else os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select POTA Prop CSV File",
            start_dir,
            "CSV Files (*.csv);;All Files (*)",
        )
        if file_path:
            self.csv_path = file_path
            if hasattr(self, "txt_csv_path"):
                self.txt_csv_path.setText(file_path)
            if hasattr(self, "btn_select_csv"):
                self.btn_select_csv.setToolTip(f"Active Log: {self.csv_path}")
            self.reload_csv()

    def reload_csv(self):
        if hasattr(self, "txt_csv_path") and self.txt_csv_path.text().strip():
            self.csv_path = self.txt_csv_path.text().strip()
        if hasattr(self, "btn_select_csv"):
            self.btn_select_csv.setToolTip(f"Active Log: {self.csv_path}" if self.csv_path else "Click to select hunter_parks.csv log file")
        if not os.path.exists(self.csv_path):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The specified file does not exist:\n{self.csv_path}",
            )
            return
        self.hunted_parks = load_hunter_csv(self.csv_path)
        total_hunted = len(self.hunted_parks)
        total_qsos = sum(p.qsos for p in self.hunted_parks.values())
        self.card_total_hunted.set_value(f"{total_hunted:,}")
        self.status_bar.showMessage(
            f"Reloaded {total_hunted:,} hunted parks ({total_qsos:,} QSOs) from {self.csv_path}"
        )
    def on_my_call_changed(self):
        call = self.txt_my_call.text().strip().upper() if hasattr(self, "txt_my_call") else ""
        self.set_operator_callsign(call)

    def set_operator_callsign(self, call: str):
        """Sets operator callsign, updates preferences, and resolves home Maidenhead grid."""
        call = str(call or "").strip().upper()
        self.my_call = call
        if hasattr(self, "txt_my_call"):
            self.txt_my_call.setText(call)
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("my_call", call)

        if not call:
            return

        # Check resolver cache first
        resolver = CallsignResolver()
        loc = resolver.lookup_user_callsign(call)
        if loc and loc.grid:
            clean_grid = loc.grid.strip().upper()
            self.home_grid = clean_grid
            settings.setValue("home_grid", clean_grid)
            if not self.p2p_mode:
                self.current_grid = clean_grid
                if hasattr(self, "txt_grid"):
                    self.txt_grid.setText(clean_grid)
                h_lat, h_lon = maidenhead_to_latlon(clean_grid)
                if h_lat is not None and h_lon is not None:
                    self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                    if self.lightning_summary:
                        self.update_map_lightning(self.lightning_summary)
                    if hasattr(self, "map_server") and self.map_server:
                        self.map_server.update_data("home_lat", h_lat)
                        self.map_server.update_data("home_lon", h_lon)

                if hasattr(self, "card_unique_parks"):
                    self.recompute_comparisons()
                if hasattr(self, "card_weather"):
                    self.refresh_weather_display(force_refresh=True)
            name_str = f" ({loc.name})" if loc.name else ""
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage(
                    f"Callsign {call} found -> Home Grid set to {clean_grid}{name_str}", 5000
                )
        else:
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage(f"Looking up license/location for callsign {call}...")
            worker = CallsignLookupWorker(call)
            worker.signals.finished.connect(self.on_callsign_lookup_finished)
            self._run_worker(worker)

    @pyqtSlot(object)
    def on_callsign_lookup_finished(self, loc):
        if not loc:
            return
        grid_val = getattr(loc, "grid", None) if hasattr(loc, "grid") else (loc if isinstance(loc, str) else "")
        call_val = getattr(loc, "callsign", "") if hasattr(loc, "callsign") else self.my_call
        name_val = getattr(loc, "name", "") if hasattr(loc, "name") else ""
        if grid_val and (not call_val or self.my_call.strip().upper() == str(call_val).strip().upper()):
            clean_grid = str(grid_val).strip().upper()
            self.home_grid = clean_grid
            settings = QSettings("POTA", "HunterComparator")
            settings.setValue("home_grid", clean_grid)
            if not self.p2p_mode:
                self.current_grid = clean_grid
                if hasattr(self, "txt_grid"):
                    self.txt_grid.setText(clean_grid)
                h_lat, h_lon = maidenhead_to_latlon(clean_grid)
                if h_lat is not None and h_lon is not None:
                    self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                    if self.lightning_summary:
                        self.update_map_lightning(self.lightning_summary)
                    if hasattr(self, "map_server") and self.map_server:
                        self.map_server.update_data("home_lat", h_lat)
                        self.map_server.update_data("home_lon", h_lon)

                if hasattr(self, "card_unique_parks"):
                    self.recompute_comparisons()
                if hasattr(self, "card_weather"):
                    self.refresh_weather_display(force_refresh=True)
            name_str = f" ({name_val})" if name_val else ""
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage(
                    f"Callsign {call_val or self.my_call} verified -> Home Grid set to {clean_grid}{name_str}", 5000
                )

    def on_grid_changed(self):
        grid = self.txt_grid.text().strip().upper()
        if not grid:
            grid = self.home_grid or DEFAULT_HOME_GRID
        self.current_grid = grid
        self.txt_grid.setText(grid)
        if not self.p2p_mode:
            self.home_grid = grid
            settings = QSettings("POTA", "HunterComparator")
            settings.setValue("home_grid", grid)
        h_lat, h_lon = maidenhead_to_latlon(grid)
        if h_lat is not None and h_lon is not None:
            self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
            if self.lightning_summary:
                self.update_map_lightning(self.lightning_summary)
        self.recompute_comparisons()
        self.refresh_weather_display(force_refresh=True)
        self.status_bar.showMessage(
            f"Operating Grid set to {grid} | Recalculated all distances, bearings & propagation"
        )

    def on_refresh_interval_changed(self, index: int):
        intervals = [0, 30000, 60000, 120000, 300000]
        ms = intervals[index] if 0 <= index < len(intervals) else 60000
        self.refresh_timer.stop()
        if ms > 0:
            self.refresh_timer.start(ms)
            secs = ms // 1000
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage(f"Auto-refresh set to every {secs} seconds")
        else:
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage("Auto-refresh turned off (manual fetch only)")
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("refresh_interval_idx", index)

    def _run_worker(self, worker: QRunnable):
        """Starts a worker in threadpool while retaining a reference to prevent early GC."""
        self._active_workers.append(worker)

        def cleanup(*args):
            if worker in self._active_workers:
                try:
                    self._active_workers.remove(worker)
                except ValueError:
                    pass

        if hasattr(worker, "signals"):
            if hasattr(worker.signals, "finished"):
                worker.signals.finished.connect(cleanup)
            if hasattr(worker.signals, "error"):
                worker.signals.error.connect(cleanup)
        self.threadpool.start(worker)

    def fetch_spots(self):
        if self._is_fetching:
            return
        self._is_fetching = True
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("Fetching...")
        self.status_bar.showMessage("Fetching live active POTA spots...")

        worker = FetchPotaWorker()
        worker.signals.finished.connect(self.on_spots_fetched)
        worker.signals.error.connect(self.on_spots_error)
        self._run_worker(worker)

    def fetch_solar(self):
        worker = FetchSolarWorker()
        worker.signals.finished.connect(self.on_solar_fetched)
        self._run_worker(worker)

    def fetch_aurora(self, force_refresh: bool = False):
        worker = FetchAuroraWorker(force_refresh=force_refresh)
        worker.signals.finished.connect(self.on_aurora_fetched)
        self._run_worker(worker)

    def fetch_lightning(self):
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if home_lat is None or home_lon is None:
            home_lat, home_lon = 38.3125, -81.7083
        worker = FetchLightningWorker(home_lat, home_lon)
        worker.signals.finished.connect(self.on_lightning_fetched)
        self._run_worker(worker)

    @pyqtSlot(object)
    def on_solar_fetched(self, solar_weather):
        if solar_weather is not None:
            self.solar_weather = solar_weather
            self.last_swpc_fetch_time = time.time()
            if hasattr(self, "lbl_status_swpc"):
                self.update_widget_history(self.lbl_status_swpc, f"SFI: {int(solar_weather.sfi)}, K: {int(solar_weather.k_index)} ({solar_weather.condition})")

    @pyqtSlot(list)
    def on_aurora_fetched(self, lines: list):
        if lines:
            self.aurora_lines = lines
            self.last_aurora_fetch_time = time.time()
            if self.map_window:
                self.map_window.update_aurora(lines)
            if self.map_server:
                self.map_server.update_data("aurora", lines)

    @pyqtSlot(object)
    def on_lightning_fetched(self, lightning_summary):
        if lightning_summary is not None:
            self.lightning_summary = lightning_summary
            self.last_ltng_fetch_time = time.time()
            self.update_map_lightning(self.lightning_summary)
            if hasattr(self, "lbl_status_ltng"):
                act = lightning_summary.get_activity_level()
                self.update_widget_history(self.lbl_status_ltng, f"Level {act.level} ({act.label})")

    @pyqtSlot(list)
    def on_spots_fetched(
        self,
        spots: List[ActiveSpot],
        solar_weather: Optional[SolarWeather] = None,
        lightning_summary: Optional[RegionalLightningSummary] = None,
    ):
        if solar_weather is not None:
            self.solar_weather = solar_weather
        if lightning_summary is not None:
            self.lightning_summary = lightning_summary
        self._is_fetching = False
        self.last_pota_fetch_time = time.time()
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch Spots")
        self.active_spots = spots
        
        # Queue up to 5 digital activators for PSKReporter polling (prioritize VHF/6m)
        import random
        digital_spots = [s for s in spots if str(s.mode).upper() in ("FT8", "FT4", "DIGITAL") and not getattr(s, 'is_qrt', False)]
        
        def band_priority(s):
            b = str(s.band).lower()
            if b in ("6m", "2m", "70cm"): return 0
            if b in ("160m", "10m", "12m"): return 1
            return 2
            
        digital_spots.sort(key=lambda s: (band_priority(s), random.random()))
        
        added = 0
        for s in digital_spots:
            if added >= 5:
                break
            if s.activator not in self.activator_psk_cache and s.activator not in self.activator_psk_queue:
                self.activator_psk_queue.append(s.activator)
                added += 1
                
        self.recompute_comparisons()
        if hasattr(self, "lbl_status_pota"):
            self.update_widget_history(self.lbl_status_pota, f"Fetched {len(spots)} active spots")

    @pyqtSlot()
    def fetch_psk_spots(self):
        if not hasattr(self, 'rbn_nodes_list') or not self.rbn_nodes_list:
            return
            
        # Get next node to query
        if self._current_psk_node_idx >= len(self.rbn_nodes_list):
            self._current_psk_node_idx = 0
            
        node = self.rbn_nodes_list[self._current_psk_node_idx]
        self._current_psk_node_idx += 1
        
        worker = FetchPSKWorker(node)
        worker.signals.finished.connect(lambda spots, n=node: self.on_psk_fetched(spots, n))
        self._run_worker(worker)

    @pyqtSlot(list, str)
    def on_psk_fetched(self, spots, node):
        self.last_psk_fetch_time = time.time()
        if spots:
            self.psk_spots.extend(spots)
            
        # Deduplicate and expire old spots (older than 30 mins)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        seen = set()
        unique_spots = []
        for s in self.psk_spots:
            age = (now - s.time_utc).total_seconds() / 60.0
            if age > 30.0:
                continue
                
            key = (s.rx_call, s.tx_call, s.freq_mhz, s.time_utc)
            if key not in seen:
                seen.add(key)
                unique_spots.append(s)
                
        self.psk_spots = unique_spots
        self.recompute_comparisons()
        
        decode_count = len(spots) if spots else 0
        hit_count = 0
        if spots and hasattr(self, 'active_spots'):
            active_activators = {s.activator.upper() for s in self.active_spots if hasattr(s, 'activator')}
            pota_hits = [s for s in spots if s.tx_call.upper() in active_activators]
            hit_count = len(pota_hits)
            
        if hasattr(self, "lbl_status_pskr"):
            self.update_widget_history(self.lbl_status_pskr, f"Node {node}: {decode_count} decodes, {hit_count} POTA hits")

    @pyqtSlot()
    def process_activator_psk_queue(self):
        if not self.activator_psk_queue:
            return
            
        # Clean cache (remove entries older than 30 mins)
        now = time.time()
        self.activator_psk_cache = {k: v for k, v in self.activator_psk_cache.items() if now - v < 1800}
        
        # Pull next un-cached activator
        activator_call = None
        while self.activator_psk_queue:
            candidate = self.activator_psk_queue.pop(0)
            if candidate not in self.activator_psk_cache:
                activator_call = candidate
                break
                
        if not activator_call:
            return
            
        self.activator_psk_cache[activator_call] = now
        worker = FetchActivatorPSKWorker(activator_call)
        worker.signals.finished.connect(self.on_activator_psk_fetched)
        self._run_worker(worker)

    @pyqtSlot(list)
    def on_activator_psk_fetched(self, spots):
        if not spots:
            return
            
        # Filter spots: only keep them if the receiver is somewhat near the hunter (e.g. same region/continent)
        # Otherwise, an activator heard in Japan will artificially light up the hunter's (in USA) map to Texas.
        from data_engine import maidenhead_to_latlon
        from propagation_engine import calculate_distance_and_bearing
        h_lat, h_lon = maidenhead_to_latlon(self.home_grid)
        
        valid_spots = []
        for s in spots:
            if not s.rx_grid or len(s.rx_grid) < 4:
                continue
            r_lat, r_lon = maidenhead_to_latlon(s.rx_grid)
            if h_lat and h_lon and r_lat and r_lon:
                dist, _ = calculate_distance_and_bearing(h_lat, h_lon, r_lat, r_lon)
                # If the receiver is within 1500km of the hunter, it's regionally relevant
                if dist <= 1500.0:
                    valid_spots.append(s)
                    
        if not valid_spots:
            return
            
        # Append new spots to our master psk_spots list
        self.psk_spots.extend(valid_spots)
        
        # Deduplicate spots just in case
        seen = set()
        unique_spots = []
        for s in self.psk_spots:
            key = (s.rx_call, s.tx_call, s.freq_mhz, s.time_utc)
            if key not in seen:
                seen.add(key)
                unique_spots.append(s)
                
        self.psk_spots = unique_spots
        self.recompute_comparisons()

    def on_spots_error(self, err_msg: str):
        self._is_fetching = False
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch Spots")
        self.status_bar.showMessage(f"Fetch Error: {err_msg}", 5000)

    def _check_nws_warnings(self):
        """Checks if the user's location is inside any active NWS warnings and triggers popups."""
        if not self.lightning_summary or not self.lightning_summary.nws_warnings:
            return
            
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if home_lat is None or home_lon is None:
            home_lat, home_lon = 38.3125, -81.7083
            
        for w in self.lightning_summary.nws_warnings:
            if w.headline in self.acknowledged_nws_warnings:
                continue
                
            if w.polygon_coords and point_in_polygon(home_lon, home_lat, w.polygon_coords):
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle(f"Active {w.event_type}")
                
                expires_str = f"Expires in {w.expires_in_minutes} minutes" if w.expires_in_minutes else "Expiration unknown"
                
                text = (
                    f"<b>{w.event_type}</b><br><br>"
                    f"{w.headline}<br><br>"
                    f"<i>{expires_str}</i><br><br>"
                    f"Your current location is inside the active warning polygon for this weather event."
                )
                msg.setText(text)
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                btn = msg.button(QMessageBox.StandardButton.Ok)
                if btn:
                    btn.setText("Acknowledge")
                msg.exec()
                
                self.acknowledged_nws_warnings.add(w.headline)

    def refresh_lightning_display(self):
        """
        Lightweight real-time refresh of regional lightning activity,
        threat level card badge, mouseover tooltip, and band noise floor cards.
        """
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if home_lat is None or home_lon is None:
            home_lat, home_lon = 38.3125, -81.7083

        self.lightning_summary = fetch_regional_lightning_summary(home_lat, home_lon, force_refresh=True)
        self.update_map_lightning(self.lightning_summary)
        self._check_nws_warnings()

        # Update Lightning Card & Tooltip
        act = self.lightning_summary.get_activity_level()
        self.card_lightning.set_value(str(act.level))
        self.card_lightning.set_accent_color(act.color)
        self.card_lightning.setToolTip(self.lightning_summary.format_tooltip_html())

        # Update Band Noise Floor Card & Tooltip
        noise_matrix = compute_band_noise_matrix(
            home_lat,
            home_lon,
            solar_weather=self.solar_weather,
            lightning_summary=self.lightning_summary,
        )
        s_40 = next((b.s_units_label for b in noise_matrix if b.band == "40m"), "S0")
        s_20 = next((b.s_units_label for b in noise_matrix if b.band == "20m"), "S0")
        s_40_short = s_40.split()[0]
        s_20_short = s_20.split()[0]
        self.card_noise.set_value(f"40m:{s_40_short} | 20m:{s_20_short}")

        if any(b.s_units_val >= 7.0 for b in noise_matrix):
            self.card_noise.set_accent_color("#f85149")
        elif any(b.is_elevated_qrn for b in noise_matrix):
            self.card_noise.set_accent_color("#ffa657")
        else:
            self.card_noise.set_accent_color("#58a6ff")

        self.card_noise.setToolTip(self._format_noise_tooltip_html(noise_matrix))

        # If spots are loaded, recalculate spot scores with updated lightning QRN surge
        if self.active_spots:
            self.recompute_comparisons()

    def refresh_weather_display(self, force_refresh: bool = False):
        """Asynchronously fetches local weather summary from Open-Meteo and updates UI."""
        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if home_lat is None or home_lon is None:
            home_lat, home_lon = 38.3125, -81.7083

        loc_name = None
        if self.p2p_mode and self.p2p_my_park:
            p_name = getattr(self, "p2p_my_park_name", "")
            loc_name = f"{p_name} ({self.p2p_my_park})" if p_name else f"Park {self.p2p_my_park}"
        elif self.current_grid:
            loc_name = f"Home QTH ({self.current_grid})"

        worker = FetchWeatherWorker(home_lat, home_lon, location_name=loc_name, force_refresh=force_refresh)
        worker.signals.finished.connect(self._on_weather_fetched)
        self.threadpool.start(worker)

    def _on_weather_fetched(self, summary: WeatherForecastSummary):
        """Updates the Local Weather stat card value and tooltip HTML upon worker completion."""
        self.weather_summary = summary
        self.last_wx_fetch_time = time.time()
        if summary and summary.current:
            val_str = f"{int(round(summary.current.temp_f))}°F {summary.current.weather_icon} {summary.current.short_label}"
            self.card_weather.set_value(val_str)
            if hasattr(self, "lbl_status_wx"):
                self.update_widget_history(self.lbl_status_wx, f"{int(round(summary.current.temp_f))}°F, {summary.current.short_label}")
            if "Sun" in summary.current.short_label or "Clear" in summary.current.short_label:
                self.card_weather.set_accent_color("#e3b341")
            elif "Rain" in summary.current.short_label or "Storm" in summary.current.short_label or "Showers" in summary.current.short_label:
                self.card_weather.set_accent_color("#f85149")
            else:
                self.card_weather.set_accent_color("#58a6ff")
        elif summary and summary.error_message:
            self.card_weather.set_value("Error")
            self.card_weather.set_accent_color("#f85149")
        else:
            self.card_weather.set_value("--°F")
            self.card_weather.set_accent_color("#8b949e")

        if summary:
            self.card_weather.setToolTip(summary.format_tooltip_html())

    def update_p2p_ui_visibility(self):
        enabled = self.chk_p2p.isChecked()
        self.lbl_p2p_park.setVisible(enabled)
        self.txt_p2p_park.setVisible(enabled)

    def on_p2p_toggled(self, checked: bool):
        self.p2p_mode = checked
        self.update_p2p_ui_visibility()
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("p2p_mode", self.p2p_mode)

        if checked:
            if self.p2p_my_park:
                self.on_p2p_park_changed()
            else:
                self.recompute_comparisons()
        else:
            # Revert single Grid window back to Home QTH
            self.current_grid = self.home_grid
            self.txt_grid.setText(self.home_grid)
            h_lat, h_lon = maidenhead_to_latlon(self.home_grid)
            if h_lat is not None and h_lon is not None:
                self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                if self.lightning_summary:
                    self.update_map_lightning(self.lightning_summary)
            self.status_bar.showMessage(
                f"P2P Mode disabled -> Grid reverted to home QTH {self.home_grid}"
            )
            self.recompute_comparisons()
            self.refresh_weather_display(force_refresh=True)

    def on_p2p_park_changed(self):
        raw_park = self.txt_p2p_park.text().strip()
        if not raw_park:
            self.p2p_my_park = ""
            settings = QSettings("POTA", "HunterComparator")
            settings.setValue("p2p_my_park", "")
            if not self.p2p_mode:
                self.current_grid = self.home_grid
                self.txt_grid.setText(self.home_grid)
            h_lat, h_lon = maidenhead_to_latlon(self.current_grid)
            if h_lat is not None and h_lon is not None:
                self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                if self.lightning_summary:
                    self.update_map_lightning(self.lightning_summary)
            self.recompute_comparisons()
            self.refresh_weather_display(force_refresh=True)
            return

        norm_ref = normalize_ref(raw_park)
        self.p2p_my_park = norm_ref
        self.txt_p2p_park.setText(norm_ref)

        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("p2p_my_park", norm_ref)

        # 1. Immediate sync check (active spots or local disk cache)
        info = fetch_park_info(norm_ref, self.active_spots)
        if info and info.get("grid"):
            grid = info["grid"]
            self.current_grid = grid
            self.txt_grid.setText(grid)
            h_lat, h_lon = maidenhead_to_latlon(grid)
            if h_lat is not None and h_lon is not None:
                self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                if self.lightning_summary:
                    self.update_map_lightning(self.lightning_summary)
            park_name = info.get("name", "")
            self.p2p_my_park_name = park_name
            name_str = f" ({park_name})" if park_name else ""
            if park_name:
                self.txt_p2p_park.setToolTip(f"{norm_ref} - {park_name} [Grid: {grid}]")
                self.lbl_p2p_park.setToolTip(f"Field Park: {norm_ref} - {park_name}")
            else:
                self.txt_p2p_park.setToolTip(f"Your field park reference: {norm_ref}")
            self.status_bar.showMessage(
                f"Park {norm_ref}{name_str} -> Grid set to {grid} | Recalculated P2P path & propagation"
            )
            self.recompute_comparisons()
            self.refresh_weather_display(force_refresh=True)
        else:
            # 2. Asynchronous API fetch
            self.status_bar.showMessage(f"Looking up location and Maidenhead grid for {norm_ref}...")
            worker = ParkLookupWorker(norm_ref, self.active_spots)
            worker.signals.finished.connect(self.on_p2p_park_lookup_finished)
            self._run_worker(worker)
            self.recompute_comparisons()

    @pyqtSlot(dict)
    def on_p2p_park_lookup_finished(self, info: dict):
        if not info:
            return
        ref = info.get("reference")
        # Ensure user hasn't changed the input in the meantime
        if self.p2p_mode and self.p2p_my_park == ref:
            grid = info.get("grid")
            if grid:
                self.current_grid = grid
                self.txt_grid.setText(grid)
                h_lat, h_lon = maidenhead_to_latlon(grid)
                if h_lat is not None and h_lon is not None:
                    self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                    if self.lightning_summary:
                        self.update_map_lightning(self.lightning_summary)
                park_name = info.get("name", "")
                self.p2p_my_park_name = park_name
                name_str = f" ({park_name})" if park_name else ""
                if park_name:
                    self.txt_p2p_park.setToolTip(f"{ref} - {park_name} [Grid: {grid}]")
                    self.lbl_p2p_park.setToolTip(f"Field Park: {ref} - {park_name}")
                else:
                    self.txt_p2p_park.setToolTip(f"Your field park reference: {ref}")
                self.status_bar.showMessage(
                    f"Park {ref}{name_str} -> Grid set to {grid} | Recalculated P2P path & propagation"
                )
                self.recompute_comparisons()
                self.refresh_weather_display(force_refresh=True)

    def on_station_config_changed(self):
        pwr_data = self.combo_power.currentData()
        if pwr_data is not None:
            self.tx_power = float(pwr_data)
        ant_data = self.combo_antenna.currentData()
        if ant_data:
            self.antenna_type = str(ant_data)

        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("tx_power", self.tx_power)
        settings.setValue("antenna_type", self.antenna_type)

        ant_name = ANTENNA_PRESETS.get(self.antenna_type, {}).get("name", self.antenna_type)
        self.status_bar.showMessage(
            f"Station updated: {int(self.tx_power)}W | {ant_name} -> Recalculated RF propagation scores"
        )
        self.recompute_comparisons()

    def recompute_comparisons(self):
        self.compared_spots = compare_active_spots(
            spots=self.active_spots,
            hunted_map=self.hunted_parks,
            home_grid=self.current_grid,
            solar_weather=self.solar_weather,
            p2p_mode=self.p2p_mode,
            p2p_my_park=self.p2p_my_park,
            p2p_grid=self.current_grid,
            tx_power_watts=self.tx_power,
            antenna_type=self.antenna_type,
            op_call=self.my_call,
            psk_spots=getattr(self, 'psk_spots', []),
            lightning_summary=self.lightning_summary,
            fast_mode=True,
            cache_map=self.spot_cache
        )
        self.regional_matrix = getattr(compare_active_spots, "last_regional_matrix", None)

        # Dispatch heavy math to background thread
        worker = PhysicsWorker(
            spots=self.active_spots,
            hunted_map=self.hunted_parks,
            home_grid=self.current_grid,
            solar_weather=self.solar_weather,
            p2p_mode=self.p2p_mode,
            p2p_my_park=self.p2p_my_park,
            p2p_grid=self.current_grid,
            tx_power_watts=self.tx_power,
            antenna_type=self.antenna_type,
            op_call=self.my_call,
            psk_spots=getattr(self, 'psk_spots', []),
            lightning_summary=self.lightning_summary
        )
        worker.signals.finished.connect(self.on_physics_complete)
        self._run_worker(worker)

        # Update stats
        new_count = sum(1 for c in self.compared_spots if c.is_new and self.get_worked_status(c.spot.reference) is None)
        hunted_count = sum(1 for c in self.compared_spots if not c.is_new or self.get_worked_status(c.spot.reference) is not None)
        unique_active_parks = len(set(c.spot.reference for c in self.compared_spots if c.spot.reference))

        if self.p2p_mode and self.p2p_my_park:
            p2p_count = sum(1 for c in self.compared_spots if c.is_p2p_eligible)
            self.card_unique_parks.set_title("P2P Available")
            self.card_unique_parks.set_value(f"{p2p_count}")
        else:
            self.card_unique_parks.set_title("Active Parks")
            self.card_unique_parks.set_value(f"{unique_active_parks}")

        self.card_new.set_value(f"{new_count}")
        self.card_hunted.set_value(f"{hunted_count}")
        self.card_active.set_value(f"{len(self.compared_spots)}")

        # Update Space Weather card
        from drap_engine import get_drap_haf
        home_lat, home_lon = maidenhead_to_latlon(self.home_grid)
        haf_val = get_drap_haf(home_lat, home_lon) if home_lat is not None else 0.0
        haf_str = f"HAF: {haf_val:.1f}" if haf_val > 0 else "HAF: --"

        ov_lbl, ov_col, _ = self.solar_weather.get_overall_assessment()
        flare_str = self.solar_weather.xray_class if self.solar_weather.xray_class else "Normal"
        self.card_solar.set_value(
            f"SSN: {self.solar_weather.ssn} | SFI: {int(self.solar_weather.sfi)} | A: {int(self.solar_weather.a_index)} | K: {int(self.solar_weather.k_index)} | Flare: {flare_str} | {haf_str}"
        )
        self.card_solar.set_accent_color(ov_col)
        
        base_tooltip = self.solar_weather.format_tooltip_html()
        haf_tooltip = f"<hr style='border: 1px solid #30363d; margin: 8px 0;'>"
        if haf_val < 0.5:
            haf_tooltip += f"<div style='font-size: 11px; margin-bottom: 2px;'><span style='color: #79c0ff;'>☀️ Overhead D-RAP (HAF):</span> None</div>"
            haf_tooltip += f"<div style='color: #8b949e; margin-bottom: 2px; font-size: 11px;'>There is no daytime absorption taking place overhead.</div>"
        else:
            haf_tooltip += f"<div style='font-size: 11px; margin-bottom: 2px;'><span style='color: #79c0ff;'>☀️ Overhead D-RAP (HAF):</span> {haf_val:.1f} MHz</div>"
            haf_tooltip += f"<div style='color: #8b949e; margin-bottom: 2px; font-size: 11px;'>Signals below {haf_val:.1f} MHz will suffer severe daytime absorption overhead.</div>"
        if base_tooltip.endswith("</div>"):
            self.card_solar.setToolTip(base_tooltip[:-6] + haf_tooltip + "</div>")
        else:
            self.card_solar.setToolTip(base_tooltip + haf_tooltip)

        # Update Meteor Activity card
        if hasattr(self.solar_weather, 'meteor_activity') and self.solar_weather.meteor_activity:
            meteor = self.solar_weather.meteor_activity
            self.card_meteor.set_value(f"ZHR: {meteor.zhr} | {meteor.active_shower}")
            if meteor.activity_level == "Storm":
                meteor_col = "#bc8cff" # purple
            elif meteor.activity_level == "High":
                meteor_col = "#f85149" # red
            elif meteor.activity_level == "Moderate":
                meteor_col = "#d29922" # yellow
            else:
                meteor_col = "#8b949e" # gray
            self.card_meteor.set_accent_color(meteor_col)
            self.card_meteor.setToolTip(meteor.format_tooltip_html())
        else:
            self.card_meteor.set_value("ZHR: -- | Shower: --")

        # Update Lightning Activity card (1 to 10 scale)
        if self.lightning_summary is None:
            home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
            if home_lat is not None and home_lon is not None:
                self.lightning_summary = fetch_regional_lightning_summary(home_lat, home_lon)
            else:
                self.lightning_summary = RegionalLightningSummary()
        self._check_nws_warnings()

        act = self.lightning_summary.get_activity_level()
        self.card_lightning.set_value(str(act.level))
        self.card_lightning.set_accent_color(act.color)
        self.card_lightning.setToolTip(self.lightning_summary.format_tooltip_html())
        
        self.update_map_lightning(self.lightning_summary)

        # Update Band Noise Floor card
        h_lat, h_lon = maidenhead_to_latlon(self.current_grid)
        if h_lat is not None and h_lon is not None:
            noise_matrix = compute_band_noise_matrix(
                h_lat,
                h_lon,
                solar_weather=self.solar_weather,
                lightning_summary=self.lightning_summary,
            )
            s_40 = next((b.s_units_label for b in noise_matrix if b.band == "40m"), "S0")
            s_20 = next((b.s_units_label for b in noise_matrix if b.band == "20m"), "S0")
            s_40_short = s_40.split()[0]
            s_20_short = s_20.split()[0]
            self.card_noise.set_value(f"40m:{s_40_short} | 20m:{s_20_short}")

            # Accent color: Red if high noise, Orange if elevated QRN, Blue if normal
            if any(b.s_units_val >= 7.0 for b in noise_matrix):
                self.card_noise.set_accent_color("#f85149")
            elif any(b.is_elevated_qrn for b in noise_matrix):
                self.card_noise.set_accent_color("#ffa657")
            else:
                self.card_noise.set_accent_color("#58a6ff")

            self.card_noise.setToolTip(self._format_noise_tooltip_html(noise_matrix))


        # We skip pushing to the map during the fast pass because the scores are dummy cache/pending values.
        # We will push to the map once the background PhysicsWorker finishes and returns the true QSO scores.
        self.apply_filters()

    @pyqtSlot(list, object)
    def on_physics_complete(self, compared_spots, regional_matrix):
        """Called when the background physics thread finishes computing QSO scores."""
        # 1. Update the cache
        for cs in compared_spots:
            cache_key = f"{cs.spot.activator}_{cs.spot.reference}_{cs.spot.frequency_khz}"
            self.spot_cache[cache_key] = cs.propagation

        self.compared_spots = compared_spots
        self.regional_matrix = regional_matrix
        
        # 2. Update table in place instead of a full tear-down/rebuild
        self._update_table_scores_in_place()
        
        # 3. Now that we have the real fully calculated RF physics data, push it to the map
        # This will redraw the markers AND re-trigger the propagation heat map overlay
        # using the verified local spotter evidence!
        if (self.map_window and self.map_window.isVisible()) or self.map_server:
            if not getattr(self, '_has_initial_heatmap', False) and len(self.compared_spots) > 0:
                self.push_all_data_to_map()
            else:
                self.update_map_spots_only()
            
        self.status_bar.showMessage(f"Loaded {len(compared_spots)} active spots with propagated QSO scores.", 5000)

    def _update_table_scores_in_place(self):
        """Updates just the Score and Distance cells in the table to avoid scrolling jumps."""
        # To avoid jumping, we iterate through the existing rows and find the matching ComparedSpot
        # and just update the item text/colors!
        
        # For fast lookup
        spot_map = {}
        for cs in self.compared_spots:
            cache_key = f"{cs.spot.activator}_{cs.spot.reference}_{cs.spot.frequency_khz}"
            spot_map[cache_key] = cs

        for row in range(self.table.rowCount()):
            # The full ComparedSpot object was stored in Qt.ItemDataRole.UserRole on the status cell (col 0) during apply_filters
            item_status = self.table.item(row, 0)
            if not item_status:
                continue
                
            old_cs = item_status.data(Qt.ItemDataRole.UserRole)
            if not old_cs or not hasattr(old_cs, 'spot'):
                continue
                
            cache_key = f"{old_cs.spot.activator}_{old_cs.spot.reference}_{old_cs.spot.frequency_khz}"
            cs = spot_map.get(cache_key)
            if cs:
                # Update Score (Column 1)
                item_score = self.table.item(row, 1)
                if item_score:
                    prob = cs.dx_percentage
                    has_local = cs.has_local_evidence
                    if prob >= 99:
                        prob_text = f"{prob} !" if has_local else f"{prob}"
                        prob_color = "#2ea043"  # Green
                    elif prob >= 75:
                        prob_text = f"{prob} +" if has_local else f"{prob}"
                        prob_color = "#d29922"  # Yellow
                    elif prob >= 50:
                        prob_text = f"{prob} +" if has_local else f"{prob}"
                        prob_color = "#f78166"  # Orange
                    else:
                        prob_text = "0" if prob == 0 else f"{prob}"
                        if has_local and prob > 0: prob_text += " +"
                        prob_color = "#da3633"  # Red

                    item_score.setText(prob_text)
                    if hasattr(item_score, 'sort_value'):
                        item_score.sort_value = float(prob)
                    item_score.setForeground(QBrush(QColor(prob_color)))
                    font = item_score.font()
                    font.setBold(True)
                    item_score.setFont(font)
                    item_score.setToolTip(self.build_row_tooltip(cs))
                
                # Update Distance (Column 10)
                item_dist = self.table.item(row, 10)
                if item_dist:
                    dist = cs.propagation.distance_miles if cs.propagation and cs.propagation.distance_miles is not None else float('inf')
                    dist_str = f"{int(dist):,} mi" if dist != float('inf') else "-"
                    item_dist.setText(dist_str)
                    if hasattr(item_dist, 'sort_value'):
                        item_dist.sort_value = float(dist)
                    
                # The map popups are updated by update_map_spots_only() so we don't need to do it here


    def reset_filters(self):
        self.combo_status.setCurrentIndex(0)
        self.combo_dx.setCurrentIndex(0)
        self.combo_band.setCurrentIndex(0)
        self.combo_mode.setCurrentIndex(0)
        self.txt_search.clear()
        self.apply_filters()

    def apply_filters(self):
        status_filter = self.combo_status.currentIndex()  # 0: All, 1: New, 2: Hunted, 3: P2P
        dx_filter_idx = self.combo_dx.currentIndex()  # 0: All, 1: >=25%, 2: >=50%, 3: >=75%
        band_filter = self.combo_band.currentText()
        mode_filter = self.combo_mode.currentText()
        search_text = self.txt_search.text().strip().lower()

        # Save filter preferences in QSettings so they persist
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("filter_status_idx", status_filter)
        settings.setValue("filter_dx_idx", dx_filter_idx)
        settings.setValue("filter_band", band_filter)
        settings.setValue("filter_mode", mode_filter)

        # Score threshold per dropdown index: 0=All, 1=>=25, 2=>=50, 3=>=75, 4=>=99 (Exceptional)
        dx_thresholds = [0, 25, 50, 75, 99]
        min_dx_pct = dx_thresholds[dx_filter_idx] if dx_filter_idx < len(dx_thresholds) else 0

        filtered: List[ComparedSpot] = []
        for cs in self.compared_spots:
            worked_st = self.get_worked_status(cs.spot.reference)
            is_worked_today = (worked_st == "TODAY")
            is_worked_prev = (worked_st == "PREVIOUS_DAY")
            is_ever_worked = is_worked_today or is_worked_prev
            is_effectively_new = cs.is_new and not is_ever_worked

            # 1. Status filter: 0=All, 1=New, 2=Hunted/Worked, 3=[WORKED] Today Only, 4=P2P
            if status_filter == 1 and not is_effectively_new:
                continue
            if status_filter == 2 and is_effectively_new:
                continue
            if status_filter == 3 and not is_worked_today:
                continue
            if status_filter == 4 and not cs.is_p2p_eligible:
                continue

            # 2. Score filter
            if cs.dx_percentage < min_dx_pct:
                continue

            # 3. Band filter
            if band_filter not in ("All", "All Bands"):
                if band_filter == "Other":
                    if cs.spot.band in [
                        "160m", "80m", "60m", "40m", "30m", "20m", "17m",
                        "15m", "12m", "10m", "6m", "2m", "70cm"
                    ]:
                        continue
                elif cs.spot.band != band_filter:
                    continue

            # 4. Mode filter
            if mode_filter not in ("All", "All Modes"):
                spot_m = (cs.spot.mode or "").upper().strip()
                if mode_filter == "CW":
                    if spot_m != "CW":
                        continue
                elif mode_filter == "SSB":
                    if spot_m not in ("SSB", "USB", "LSB", "PHONE"):
                        continue
                elif mode_filter == "FT8":
                    if spot_m != "FT8":
                        continue
                elif mode_filter == "FM":
                    if spot_m != "FM":
                        continue
                elif mode_filter == "AM":
                    if spot_m != "AM":
                        continue
                elif mode_filter == "DATA":
                    standard_non_other = {
                        "CW", "SSB", "USB", "LSB", "PHONE", "FT8", "FM", "AM"
                    }
                    if spot_m in standard_non_other:
                        continue
                elif spot_m != mode_filter.upper():
                    continue

            # 5. Search text filter
            if search_text:
                matchable = " ".join(
                    [
                        cs.spot.reference,
                        cs.display_name,
                        cs.spot.activator,
                        cs.spot.location_desc,
                        cs.display_location,
                        cs.spot.grid4,
                        cs.spot.grid6,
                        cs.spot.comments,
                    ]
                ).lower()
                if search_text not in matchable:
                    continue

            filtered.append(cs)

        self.populate_table(filtered)

    def build_row_tooltip(self, cs: ComparedSpot) -> str:
        """
        Builds a comprehensive mouseover HTML tooltip listing nearby re-spots, spot freshness,
        and QSO feasibility. If no nearby re-spots are available, explicitly outputs 'None'.
        """
        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 12px; color: #e6edf3; line-height: 1.4; padding: 4px;'>")

        # 1. Header: Station, P2P Target, & Park
        loc_desc = cs.full_location_desc
        is_same_park = cs.is_p2p_same_park
        if cs.is_p2p_eligible:
            lines.append(f"<div style='font-size: 14px; font-weight: bold; color: #ff7b72; margin-bottom: 2px;'>P2P TARGET: {cs.spot.activator}</div>")
            lines.append(f"<div style='color: #8b949e; margin-bottom: 4px;'>{cs.spot.reference} - {cs.display_name}<br><b>Location:</b> {loc_desc}<br>Park-to-Park Path from {cs.p2p_my_park or 'Field QTH'}</div>")
        elif is_same_park:
            lines.append(f"<div style='font-size: 14px; font-weight: bold; color: #79c0ff; margin-bottom: 2px;'>SAME PARK: {cs.spot.activator}</div>")
            lines.append(f"<div style='color: #8b949e; margin-bottom: 4px;'>{cs.spot.reference} - {cs.display_name}<br><b>Location:</b> {loc_desc}</div>")
        else:
            lines.append(f"<div style='font-size: 14px; font-weight: bold; color: #58a6ff; margin-bottom: 2px;'>STATION: {cs.spot.activator}</div>")
            lines.append(f"<div style='color: #8b949e; margin-bottom: 4px;'>{cs.spot.reference} - {cs.display_name}<br><b>Location:</b> {loc_desc}</div>")

        lines.append(
            f"<div style='margin-bottom: 8px;'><b>Freq:</b> <span style='color: #a5d6ff;'>{cs.frequency_mhz_str}</span> | <b>Mode:</b> <span style='color: #a5d6ff;'>{cs.spot.mode}</span> | <b>Band:</b> <span style='color: #a5d6ff;'>{cs.spot.band}</span></div>"
        )

        # 2. Spot Freshness & Decay
        exp_info = f" | Expire in ~{cs.expire_mins_remaining}m" if cs.expire_mins_remaining is not None else ""
        lines.append(f"<div style='margin-bottom: 8px;'><b>Spot Freshness:</b> {cs.time_ago_str} ({cs.decay_status}){exp_info}</div>")

        # 3. QSO Score & Propagation Path
        prob = cs.dx_percentage
        prob_color = "#3fb950" if prob >= 75 else ("#d29922" if prob >= 50 else "#f85149")
        prob_badge = (
            "Exceptional !"
            if prob >= 99
            else (
                "Strong Path"
                if prob >= 75
                else (
                    "Good Path"
                    if prob >= 50
                    else ("Fair Path" if prob >= 25 else "Weak / Closed")
                )
            )
        )
        path_sum = cs.propagation.path_summary if cs.propagation else "N/A"
        dist_info = (
            f"{int(cs.propagation.distance_miles):,} mi ({int(cs.propagation.bearing_deg)} deg)"
            if cs.propagation
            else "N/A"
        )
        lines.append(f"<div style='margin-bottom: 2px;'><b>QSO Score:</b> <span style='color: {prob_color}; font-weight: bold;'>{prob} ({prob_badge})</span> | <b>Distance:</b> {dist_info}</div>")
        if cs.spot_evidence and cs.spot_evidence.is_qrp:
            qrp_label = cs.spot_evidence.qrp_desc or "QRP (Low Power)"
            lines.append(f"<div style='margin-bottom: 2px;'><b>Activator Power:</b> <span style='color: #e3b341; font-weight: bold;'>⚡ {qrp_label}</span></div>")
        lines.append(f"<div style='margin-bottom: 8px;'><b>Propagation Path:</b> <span style='color: #8b949e;'>{path_sum}</span></div>")

        # 4. Nearby Re-spots Section
        ev = cs.spot_evidence
        op_land_tag = ev.op_land_desc if (ev and ev.op_land_desc) else "Local Area"
        lines.append(f"<hr style='border: 1px solid #30363d; margin: 8px 0;'>")
        lines.append(f"<div style='margin-bottom: 4px;'><b>Nearby Re-spots ({op_land_tag}):</b></div>")

        has_nearby = False

        if ev and ev.local_spotters:
            has_nearby = True
            lines.append("<table style='margin-left: 8px; margin-bottom: 2px; border-collapse: collapse; width: 95%;'>")
            lines.append("<tr style='border-bottom: 1px solid #30363d; color: #8b949e; text-align: left;'>")
            lines.append("<th style='padding: 2px 4px;'>Callsign</th><th style='padding: 2px 4px;'>Method</th><th style='padding: 2px 4px;'>Dist/Age</th></tr>")
            
            respot_map = {}
            for r in cs.spot.respots or []:
                call = str(r.get("spotter") or "").strip().upper()
                if call and call not in respot_map:
                    respot_map[call] = r

            for s in ev.local_spotters:
                r = respot_map.get(s.callsign.upper(), {})
                comment = str(r.get("comments") or "").strip()
                
                dist_str = f"{int(s.distance_miles)}mi" if s.distance_miles is not None else ""
                
                age_str = ""
                if hasattr(s, 'age_mins') and s.age_mins is not None:
                    age_str = f"{int(s.age_mins)}m ago"
                else:
                    time_raw = str(r.get("spotTime") or "")
                    if time_raw:
                        age_str = f"[{time_raw.replace('T', ' ')[11:16]}z]"
                
                dist_age_val = f"{dist_str} {age_str}".strip()

                method_val = getattr(s, 'method', 'POTA Spot')
                if getattr(s, 'snr', None) is not None:
                    method_val += f" ({s.snr:+.0f}dB)"
                
                comment_desc = f" title='{comment}'" if comment else ""
                
                lines.append(f"<tr{comment_desc}>")
                lines.append(f"<td style='padding: 2px 4px;'><b>{s.callsign}</b></td>")
                lines.append(f"<td style='padding: 2px 4px; color: #a5d6ff;'>{method_val}</td>")
                lines.append(f"<td style='padding: 2px 4px; color: #8b949e;'>{dist_age_val}</td>")
                lines.append("</tr>")
            
            lines.append("</table>")

        if ev and ev.local_state_mentions:
            if not has_nearby:
                has_nearby = True
            lines.append(
                f"<div style='margin-left: 8px; margin-bottom: 2px;'>• <b>State Signal Reports:</b> <i style='color: #a5d6ff;'>{', '.join(ev.local_state_mentions)}</i></div>"
            )

        if not has_nearby:
            lines.append("<div style='margin-left: 8px; color: #8b949e;'>None</div>")

        # 5. Supplemental Intelligence
        lines.append(f"<hr style='border: 1px solid #30363d; margin: 8px 0;'>")
        if ev:
            if ev.signal_reports:
                lines.append(f"<div style='margin-bottom: 2px;'><b>Signal Reports:</b> {', '.join(ev.signal_reports)}</div>")
            if ev.empirical_boost_pct != 0:
                sign = "+" if ev.empirical_boost_pct > 0 else ""
                lines.append(f"<div style='margin-bottom: 2px;'><b>Score Boost:</b> <span style='color: #3fb950;'>{sign}{ev.empirical_boost_pct}</span></div>")
                if ev.evidence_summary:
                    lines.append(f"<div style='margin-bottom: 2px; color: #8b949e; font-size: 11px;'><i>{ev.evidence_summary}</i></div>")
            if len(cs.spot.respots) > 1:
                lines.append(f"<div style='margin-bottom: 2px;'><b>Total Respots:</b> {len(cs.spot.respots)}</div>")

        if cs.propagation:
            p = cs.propagation
            gray_tag = " | <span style='color: #d29922;'>[Grayline Active: +28%]</span>" if p.is_grayline else ""
            muf_str = format_muf_telemetry(p)
            lines.append(
                f"<div style='margin-bottom: 2px;'><b>Est MUF:</b> {muf_str} | <b>SFI</b> {int(p.solar_info.sfi)}, <b>A-idx</b> {int(p.solar_info.a_index)}, <b>K-idx</b> {int(p.solar_info.k_index)}{gray_tag}</div>"
            )
            if p.predicted_snr_db is not None:
                lines.append(
                    f"<div style='margin-bottom: 2px;'><b>Ray Path:</b> <span style='color: #a5d6ff;'>{p.ray_mode}</span> (Takeoff {p.takeoff_angle_deg:.1f}&deg;, Loss {p.path_loss_db:.1f} dB) | <b>Predicted SNR:</b> <span style='color: #3fb950;'>{p.predicted_snr_db:+.1f} dB</span></div>"
                )
            ant_name = ANTENNA_PRESETS.get(p.antenna_type, {}).get("name", p.antenna_type)
            lines.append(
                f"<div style='margin-bottom: 2px; color: #8b949e;'><b>Station Link:</b> {p.tx_power_watts:.0f}W | {ant_name} ({p.antenna_gain_dbi:+.1f} dBi @ {p.takeoff_angle_deg:.1f}&deg;) | Link Offset: {p.station_offset_db:+.1f} dB</div>"
            )
            if p.qrn_surge_db > 0:
                lines.append(f"<div style='margin-bottom: 2px; color: #ff7b72;'><b>⚡ Lightning QRN Surge:</b> +{p.qrn_surge_db:.1f} dB (Local Sferic Noise)</div>")
            if getattr(p, 'drap_loss_db', 0) > 0:
                lines.append(f"<div style='margin-bottom: 2px; color: #ff7b72;'><b>☀️ D-RAP Attenuation:</b> -{p.drap_loss_db:.1f} dB (Solar Absorption)</div>")

        lines.append("</div>")
        return "".join(lines)

    def on_tooltips_toggled(self, checked: bool):
        self.show_tooltips = checked
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("show_tooltips", self.show_tooltips)
        self.apply_tooltips_to_current_table()

    def apply_tooltips_to_current_table(self):
        for row in range(self.table.rowCount()):
            item_0 = self.table.item(row, 0)
            if not item_0:
                continue
            cs: ComparedSpot = item_0.data(Qt.ItemDataRole.UserRole)
            if not cs:
                continue
            row_tooltip = self.build_row_tooltip(cs) if self.show_tooltips else ""
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    item.setToolTip(row_tooltip)

    def populate_table(self, items: List[ComparedSpot]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))

        for row, cs in enumerate(items):
            # Precompute row tooltip based on toggle state
            row_tooltip = self.build_row_tooltip(cs) if self.show_tooltips else ""

            # 0: Status Badge & Dropdown Selector (with [WORKED], Hunted(W), & P2P support)
            worked_status = self.get_worked_status(cs.spot.reference)
            is_worked_today = (worked_status == "TODAY")
            is_worked_prev = (worked_status == "PREVIOUS_DAY")

            if is_worked_today:
                raw_auto_label = "[WORKED]"
                item_status = NumericTableWidgetItem("[WORKED]", 2.0)
                item_status.setForeground(QBrush(QColor("#3fb950")))
                item_status.setFont(QFont("", -1, QFont.Weight.Bold))
            elif is_worked_prev:
                if cs.is_p2p_eligible:
                    raw_auto_label = "[P2P] Hunted(W)"
                    item_status = NumericTableWidgetItem("[P2P] Hunted(W)", 0.6)
                    item_status.setForeground(QBrush(QColor("#d2a8ff")))
                else:
                    if cs.qsos_hunted > 0:
                        raw_auto_label = f"Hunted(W) ({cs.qsos_hunted})"
                    else:
                        raw_auto_label = "Hunted(W)"
                    item_status = NumericTableWidgetItem(raw_auto_label, 0.4)
                    item_status.setForeground(QBrush(QColor("#7ee787")))
                item_status.setFont(QFont("", -1, QFont.Weight.Bold))
            elif cs.is_p2p_eligible:
                if cs.is_new:
                    raw_auto_label = "[P2P] [NEW]"
                    item_status = NumericTableWidgetItem("[P2P] [NEW]", 1.5)
                    item_status.setForeground(QBrush(QColor("#bc8cff")))
                else:
                    raw_auto_label = f"[P2P] Hunted ({cs.qsos_hunted})"
                    item_status = NumericTableWidgetItem(raw_auto_label, 0.5)
                    item_status.setForeground(QBrush(QColor("#d2a8ff")))
                item_status.setFont(QFont("", -1, QFont.Weight.Bold))
            elif cs.is_p2p_same_park:
                raw_auto_label = "[SAME PARK]"
                item_status = NumericTableWidgetItem("[SAME PARK]", 0.2)
                item_status.setForeground(QBrush(QColor("#8b949e")))
            elif cs.is_new:
                raw_auto_label = "[NEW]"
                item_status = NumericTableWidgetItem("[NEW]", 1.0)
                item_status.setForeground(QBrush(QColor("#f1e05a")))
                item_status.setFont(QFont("", -1, QFont.Weight.Bold))
            else:
                raw_auto_label = f"Hunted ({cs.qsos_hunted})"
                item_status = NumericTableWidgetItem(raw_auto_label, 0.0)
                item_status.setForeground(QBrush(QColor("#7ee787")))
            item_status.setToolTip(row_tooltip)

            # 1: Score Badge
            prob = cs.dx_percentage
            has_local = cs.has_local_evidence
            if prob >= 99:
                prob_text = f"{prob} !" if has_local else f"{prob}"
                prob_color = "#2ea043"  # Green
            elif prob >= 75:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#d29922"  # Yellow
            elif prob >= 50:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#f78166"  # Orange
            else:
                prob_text = "0" if prob == 0 else f"{prob}"
                if has_local and prob > 0: prob_text += " +"
                prob_color = "#da3633"  # Red

            item_dx = NumericTableWidgetItem(prob_text, float(prob))
            item_dx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_dx.setForeground(QBrush(QColor(prob_color)))
            item_dx.setFont(QFont("", -1, QFont.Weight.Bold))
            item_dx.setToolTip(row_tooltip)

            # 2: Park Reference
            # 2: Activator
            act_text = cs.spot.activator
            if cs.spot_evidence and cs.spot_evidence.is_qrp:
                act_text += " ⚡"
            item_call = QTableWidgetItem(act_text)
            item_call.setFont(QFont("", -1, QFont.Weight.Bold))
            item_call.setForeground(QBrush(QColor("#d29922")))
            item_call.setToolTip(row_tooltip)
            cache_key = f"{cs.spot.activator}_{cs.spot.reference}_{cs.spot.frequency_khz}"
            item_call.setData(Qt.ItemDataRole.UserRole, cache_key)

            # 3: Frequency (numeric sort by kHz)
            item_freq = NumericTableWidgetItem(cs.frequency_mhz_str, cs.spot.frequency_khz)
            item_freq.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_freq.setToolTip(row_tooltip)

            # 4: Spot Time (with Activity Decay Color Coding)
            sort_ts = cs.spot.spot_time_dt.timestamp() if cs.spot.spot_time_dt else 0.0
            item_time = NumericTableWidgetItem(cs.time_ago_str, sort_ts)
            item_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_time.setForeground(QBrush(QColor(cs.decay_color)))
            if cs.decay_status == "Fresh":
                item_time.setFont(QFont("", -1, QFont.Weight.Bold))
            item_time.setToolTip(row_tooltip)

            # 5: Park Reference
            item_ref = QTableWidgetItem(cs.spot.reference)
            item_ref.setFont(QFont("", -1, QFont.Weight.Bold))
            item_ref.setForeground(QBrush(QColor("#58a6ff")))
            item_ref.setToolTip(row_tooltip)

            # 6: Park Name
            item_name = QTableWidgetItem(cs.display_name)
            item_name.setToolTip(row_tooltip)

            # 7: Location / State
            item_loc = QTableWidgetItem(cs.display_location)
            item_loc.setToolTip(row_tooltip)

            # 8: Band
            item_band = QTableWidgetItem(cs.spot.band)
            item_band.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_band.setToolTip(row_tooltip)

            # 9: Mode
            item_mode = QTableWidgetItem(cs.spot.mode)
            item_mode.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if cs.spot.mode == "CW":
                item_mode.setForeground(QBrush(QColor("#ff7b72")))
            elif cs.spot.mode == "SSB":
                item_mode.setForeground(QBrush(QColor("#79c0ff")))
            elif "FT8" in cs.spot.mode or "FT4" in cs.spot.mode:
                item_mode.setForeground(QBrush(QColor("#d2a8ff")))
            item_mode.setToolTip(row_tooltip)

            # 10: Distance & Bearing
            if cs.propagation and cs.propagation.distance_miles > 0:
                dist_str = f"{int(cs.propagation.distance_miles):,} mi ({int(cs.propagation.bearing_deg)} deg)"
                item_dist = NumericTableWidgetItem(dist_str, cs.propagation.distance_miles)
            else:
                item_dist = NumericTableWidgetItem("-", 999999.0)
            item_dist.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_dist.setToolTip(row_tooltip)

            # 11: Grid
            grid = cs.spot.grid6 or cs.spot.grid4 or "-"
            item_grid = QTableWidgetItem(grid)
            item_grid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_grid.setToolTip(row_tooltip)

            # 12: Comments
            comment_text = cs.spot.comments
            if has_local and not comment_text.startswith("+"):
                comment_text = f"+ {comment_text}" if comment_text else "+ Local 8-land spot"
            item_comments = QTableWidgetItem(comment_text)
            if has_local:
                item_comments.setForeground(QBrush(QColor("#7ee787")))
            item_comments.setToolTip(row_tooltip)

            # Store the ComparedSpot object reference on the first column item for quick retrieval
            item_status.setData(Qt.ItemDataRole.UserRole, cs)

            self.table.setItem(row, 0, item_status)
            self.table.setItem(row, 1, item_dx)
            self.table.setItem(row, 2, item_call)
            self.table.setItem(row, 3, item_freq)
            self.table.setItem(row, 4, item_time)
            self.table.setItem(row, 5, item_ref)
            self.table.setItem(row, 6, item_name)
            self.table.setItem(row, 7, item_loc)
            self.table.setItem(row, 8, item_band)
            self.table.setItem(row, 9, item_mode)
            self.table.setItem(row, 10, item_dist)
            self.table.setItem(row, 11, item_grid)
            self.table.setItem(row, 12, item_comments)



            # Add drop-down selector widget in Status column cell
            combo_status = QComboBox()
            combo_status.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if is_worked_today:
                combo_status.addItem("[WORKED]")
                combo_status.addItem("Mark as Unworked")
                combo_status.setCurrentIndex(0)
                combo_status.setStyleSheet(
                    "QComboBox { background-color: #1b4b27; color: #3fb950; border: 1px solid #2ea043; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
                    "QComboBox::drop-down { border: none; }"
                )
            elif is_worked_prev:
                combo_status.addItem(raw_auto_label)
                combo_status.addItem("Mark [WORKED] Today")
                combo_status.addItem("Clear Worked History")
                combo_status.setCurrentIndex(0)
                if cs.is_p2p_eligible:
                    combo_status.setStyleSheet(
                        "QComboBox { background-color: #2b1b3d; color: #d2a8ff; border: 1px solid #8957e5; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
                        "QComboBox::drop-down { border: none; }"
                    )
                else:
                    combo_status.setStyleSheet(
                        "QComboBox { background-color: #16231a; color: #7ee787; border: 1px solid #238636; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
                        "QComboBox::drop-down { border: none; }"
                    )
            else:
                combo_status.addItem(raw_auto_label)
                combo_status.addItem("Mark [WORKED]")
                combo_status.setCurrentIndex(0)
                if cs.is_new:
                    combo_status.setStyleSheet(
                        "QComboBox { background-color: #26210f; color: #f1e05a; border: 1px solid #d29922; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
                        "QComboBox::drop-down { border: none; }"
                    )
                else:
                    combo_status.setStyleSheet(
                        "QComboBox { background-color: #16231a; color: #7ee787; border: 1px solid #238636; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
                        "QComboBox::drop-down { border: none; }"
                    )

            target_ref = cs.spot.reference
            target_call = cs.spot.activator
            curr_w_status = worked_status

            def on_cell_status_changed(index: int, ref=target_ref, call=target_call, w_stat=curr_w_status, r=row):
                if w_stat == "TODAY":
                    if index == 1:
                        self.toggle_park_worked(ref, force_state=False, row=r)
                elif w_stat == "PREVIOUS_DAY":
                    if index == 1:
                        self.toggle_park_worked(ref, force_state=True, activator_call=call, row=r)
                    elif index == 2:
                        self.toggle_park_worked(ref, force_state=False, row=r)
                else:
                    if index == 1:
                        self.toggle_park_worked(ref, force_state=True, activator_call=call, row=r)

            combo_status.currentIndexChanged.connect(on_cell_status_changed)
            self.table.setCellWidget(row, 0, combo_status)

        self.table.setSortingEnabled(True)

    def get_selected_compared_spot(self) -> Optional[ComparedSpot]:

        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        item = self.table.item(row, 0)
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def prompt_spot_on_pota(self, park_ref: str, activator_call: str = "", row: int = -1):

        """
        Prompt dialog encouraging the hunter to re-spot the activator
        after marking a park worked.
        """
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        settings = QSettings("POTA", "HunterComparator")
        prompt_enabled = settings.value("prompt_spot_on_worked", True, type=bool)
        if not prompt_enabled:
            return

        call_str = f" with {activator_call}" if activator_call else ""
        dlg = QDialog(self)
        dlg.setWindowTitle("Spot Activator")
        dlg.setFixedSize(480, 220)
        dlg.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        lbl_title = QLabel("Re-Spot Activator?")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(lbl_title)

        msg_label = QLabel(
            f"Congratulations on working park {park_ref}{call_str}!\n\n"
            "Would you like to re-spot this activator? "
            "Re-spotting helps fellow hunters verify live propagation openings in real-time."
        )
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("color: #c9d1d9; font-size: 13px;")
        layout.addWidget(msg_label)

        chk_no_prompt = QCheckBox("Don't ask me again when marking worked")
        chk_no_prompt.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(chk_no_prompt)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_spot = QPushButton("Open Spot Dialog")
        btn_spot.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_spot.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)

        def on_spot_clicked():
            if chk_no_prompt.isChecked():
                settings.setValue("prompt_spot_on_worked", False)
            dlg.accept()
            if row >= 0:
                self.open_spot_dialog(row)
            else:
                webbrowser.open(f"https://pota.app/#/park/{park_ref}")

        btn_spot.clicked.connect(on_spot_clicked)
        btn_layout.addWidget(btn_spot)

        btn_cancel = QPushButton("Just Mark Worked")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)

        def on_cancel_clicked():
            if chk_no_prompt.isChecked():
                settings.setValue("prompt_spot_on_worked", False)
            dlg.reject()

        btn_cancel.clicked.connect(on_cancel_clicked)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)
        dlg.exec()

    def toggle_park_worked(self, park_ref: str, force_state: Optional[bool] = None, activator_call: str = "", skip_prompt: bool = False, row: int = -1):
        ref = normalize_ref(park_ref)
        if not ref:
            return
        today_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        is_now_worked = False
        if force_state is True:
            self.manually_worked_parks.add(ref, today_utc_str)
            is_now_worked = True
        elif force_state is False:
            self.manually_worked_parks.discard(ref)
        else:
            w_stat = self.get_worked_status(ref)
            if w_stat == "TODAY":
                self.manually_worked_parks.discard(ref)
            else:
                self.manually_worked_parks.add(ref, today_utc_str)
                is_now_worked = True

        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("manually_worked_parks", dict(self.manually_worked_parks))
        self.recompute_comparisons()

        if is_now_worked and not skip_prompt:
            self.prompt_spot_on_pota(ref, activator_call, row)

    def toggle_selected_park_worked(self):
        cs = self.get_selected_compared_spot()
        if cs and cs.spot.reference:
            selected_rows = self.table.selectionModel().selectedRows()
            row = selected_rows[0].row() if selected_rows else -1
            self.toggle_park_worked(cs.spot.reference, activator_call=cs.spot.activator, row=row)

    def on_table_selection_changed(self):
        cs = self.get_selected_compared_spot()
        if not cs:
            self.lbl_selection_info.setText("Select a park from the table for detailed info.")
            self.btn_open_park.setEnabled(False)
            self.btn_spot_intel.setEnabled(False)
            if hasattr(self, "btn_mark_worked"):
                self.btn_mark_worked.setEnabled(False)
                self.btn_mark_worked.setText("Mark [WORKED]")
            return

        worked_st = self.get_worked_status(cs.spot.reference)
        if hasattr(self, "btn_mark_worked"):
            self.btn_mark_worked.setEnabled(True)
            if worked_st == "TODAY":
                self.btn_mark_worked.setText("Unmark [WORKED]")
            elif worked_st == "PREVIOUS_DAY":
                self.btn_mark_worked.setText("Mark [WORKED] (Today)")
            else:
                self.btn_mark_worked.setText("Mark [WORKED]")

        if worked_st == "TODAY":
            status_text = "[WORKED TODAY]"
        elif worked_st == "PREVIOUS_DAY":
            status_text = "HUNTED(W) (Worked Previous UTC Day • Eligible to Hunt Again Today!)"
        elif cs.is_new:
            status_text = "UNHUNTED PARK"
        else:
            status_text = f"HUNTED ({cs.qsos_hunted} QSOs, First: {cs.hunted_park.first_qso_date if cs.hunted_park else 'N/A'})"
        coords = (
            f"{cs.spot.latitude:.4f}, {cs.spot.longitude:.4f}"
            if (cs.spot.latitude and cs.spot.longitude)
            else "N/A"
        )

        dx_info = ""
        if cs.propagation:
            gray_tag = " | [Grayline Active]" if cs.propagation.is_grayline else ""
            ev_tag = ""
            if cs.spot_evidence and cs.spot_evidence.empirical_boost_pct > 0:
                ev_tag = f" <span style='color:#7ee787;'>(+{cs.spot_evidence.empirical_boost_pct}% local intel)</span>"
            muf_str = format_muf_telemetry(cs.propagation)
            dx_info = (
                f"<b>Score:</b> <span style='color:#58a6ff; font-weight:bold;'>{cs.dx_percentage}</span>{ev_tag} "
                f"({cs.propagation.path_summary}) | "
                f"<b>Dist:</b> {int(cs.propagation.distance_miles):,} mi ({int(cs.propagation.bearing_deg)} deg heading) | "
                f"<b>Est MUF:</b> {muf_str}{gray_tag} | "
            )

        info_text = (
            f"<b>{cs.spot.reference}</b> - {cs.display_name} | "
            f"<b>Activator:</b> {cs.spot.activator} @ {cs.frequency_mhz_str} ({cs.spot.mode} - {cs.spot.band}) | "
            f"{dx_info}"
            f"<b>Status:</b> {status_text} | "
            f"<b>Grid:</b> {cs.spot.grid6 or cs.spot.grid4 or 'N/A'} (Lat/Lon: {coords}) | "
            f"<b>Comments:</b> {cs.spot.comments or 'None'}"
        )
        self.lbl_selection_info.setText(info_text)
        self.btn_open_park.setEnabled(bool(cs.spot.reference))
        self.btn_spot_intel.setEnabled(True)

    def on_table_double_clicked(self, item: QTableWidgetItem):
        self.open_selected_spot_intel()

    def open_selected_spot_intel(self):
        cs = self.get_selected_compared_spot()
        if cs:
            home_lat, home_lon = maidenhead_to_latlon(self.home_grid)
            if home_lat is None or home_lon is None:
                home_lat, home_lon = 38.3125, -81.7083
            dlg = SpotHistoryDialog(cs, home_lat=home_lat, home_lon=home_lon, parent=self)
            dlg.exec()

    def open_selected_park_web(self):
        cs = self.get_selected_compared_spot()
        if cs and cs.spot.reference:
            url = f"https://pota.app/#/park/{cs.spot.reference}"
            webbrowser.open(url)

    def collect_telemetry_data(self) -> dict:
        """Collects all real-time telemetry into a structured dictionary."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Spot statistics
        band_counts = {}
        top_regions_dict = {}
        for s in self.active_spots:
            b = str(getattr(s, "band", "") or "").strip()
            if b:
                band_counts[b] = band_counts.get(b, 0) + 1
            loc = str(getattr(s, "location_desc", "") or getattr(s, "park_location", "") or "").strip()
            if loc:
                top_regions_dict[loc] = top_regions_dict.get(loc, 0) + 1

        sorted_regions = sorted(top_regions_dict.items(), key=lambda x: x[1], reverse=True)[:6]

        meteor_dict = {}
        meteor_obj = getattr(self.solar_weather, "meteor_activity", None) or getattr(self, "meteor_summary", None)
        if meteor_obj:
            active_sh = getattr(meteor_obj, "active_shower", "Sporadic Background")
            meteor_dict = {
                "active_shower": active_sh,
                "active_showers": [active_sh] if (active_sh and active_sh != "Sporadic Background") else [],
                "zhr": getattr(meteor_obj, "zhr", 5),
                "peak_zhr": getattr(meteor_obj, "zhr", 5),
                "activity_level": getattr(meteor_obj, "activity_level", "Low"),
                "days_to_peak": getattr(meteor_obj, "days_to_peak", 0),
                "next_shower_name": getattr(meteor_obj, "next_shower_name", ""),
                "next_shower_days": getattr(meteor_obj, "next_shower_days", 0),
            }

        lightning_dict = {}
        if hasattr(self, "lightning_summary") and self.lightning_summary:
            lightning_dict = {
                "strikes_100km": getattr(self.lightning_summary, "strikes_100km", 0),
                "strikes_300km": getattr(self.lightning_summary, "strikes_300km", 0),
                "closest_km": getattr(self.lightning_summary, "closest_km", 999.0),
            }

        weather_dict = {}
        if hasattr(self, "station_weather") and self.station_weather:
            weather_dict = {
                "temperature_c": getattr(self.station_weather, "temperature_c", None),
                "pressure_hpa": getattr(self.station_weather, "pressure_hpa", 1013.0),
                "wind_speed_kph": getattr(self.station_weather, "wind_speed_kph", 0.0),
            }
        if hasattr(self, "weather_summary") and self.weather_summary:
            weather_dict["convective_3day"] = getattr(self.weather_summary, "convective_3day", None)
            weather_dict["home_lat"] = getattr(self.weather_summary, "home_lat", 0.0)
            weather_dict["home_lon"] = getattr(self.weather_summary, "home_lon", 0.0)

        return {
            "timestamp": now_utc,
            "my_call": self.my_call or "Operator",
            "grid": self.current_grid or self.home_grid or DEFAULT_HOME_GRID,
            "solar_weather": self.solar_weather,
            "drap_summary": getattr(self, "drap_summary", {}),
            "aurora_lines": getattr(self, "aurora_lines", []),
            "meteor_summary": meteor_dict,
            "lightning_summary": lightning_dict,
            "weather_summary": weather_dict,
            "spot_stats": {
                "total_active_spots": len(self.active_spots),
                "band_counts": band_counts,
                "top_regions": sorted_regions,
            },
        }

    def open_propagation_summary_dialog(self):
        telemetry = self.collect_telemetry_data()
        dialog = PropagationSummaryDialog(telemetry, parent=self)
        dialog.exec()

    def open_selected_qrz_web(self):
        cs = self.get_selected_compared_spot()
        if cs and cs.spot.activator:
            # Clean activator call e.g. "OZ4ABH/P" -> "OZ4ABH"
            call = cs.spot.activator.split("/")[0]
            url = f"https://www.qrz.com/db/{call}"
            webbrowser.open(url)

    def show_table_context_menu(self, pos):
        cs = self.get_selected_compared_spot()
        if not cs:
            return

        menu = QMenu(self)

        act_intel = QAction(f"View Spot Intelligence & Respot History ({cs.spot.activator})", self)
        act_intel.triggered.connect(self.open_selected_spot_intel)
        menu.addAction(act_intel)

        worked_st = self.get_worked_status(cs.spot.reference)
        if worked_st == "TODAY":
            act_worked = QAction(f"Unmark [WORKED] Status for Park {cs.spot.reference}", self)
            act_worked.triggered.connect(lambda: self.toggle_park_worked(cs.spot.reference, force_state=False))
        elif worked_st == "PREVIOUS_DAY":
            act_worked = QAction(f"Mark Park {cs.spot.reference} as [WORKED] Today (New UTC Day)", self)
            act_worked.triggered.connect(lambda: self.toggle_park_worked(cs.spot.reference, force_state=True, activator_call=cs.spot.activator))
        else:
            act_worked = QAction(f"Mark Park {cs.spot.reference} as [WORKED]", self)
            act_worked.triggered.connect(lambda: self.toggle_park_worked(cs.spot.reference, force_state=True, activator_call=cs.spot.activator))
        menu.addAction(act_worked)

        menu.addSeparator()

        act_pota = QAction(f"Open Park {cs.spot.reference} on pota.app", self)
        act_pota.triggered.connect(self.open_selected_park_web)
        menu.addAction(act_pota)

        act_qrz = QAction(f"Open Callsign {cs.spot.activator} on QRZ.com", self)
        act_qrz.triggered.connect(self.open_selected_qrz_web)
        menu.addAction(act_qrz)

        menu.addSeparator()

        act_copy_ref = QAction("Copy Park Reference", self)
        act_copy_ref.triggered.connect(lambda: QApplication.clipboard().setText(cs.spot.reference))
        menu.addAction(act_copy_ref)

        act_copy_call = QAction("Copy Activator Callsign", self)
        act_copy_call.triggered.connect(lambda: QApplication.clipboard().setText(cs.spot.activator))
        menu.addAction(act_copy_call)

        act_copy_freq = QAction("Copy Frequency", self)
        act_copy_freq.triggered.connect(lambda: QApplication.clipboard().setText(cs.frequency_mhz_str))
        menu.addAction(act_copy_freq)

        act_copy_all = QAction("Copy Full Spot Details", self)
        act_copy_all.triggered.connect(
            lambda: QApplication.clipboard().setText(
                f"{cs.status_label} | {cs.spot.reference} - {cs.display_name} | {cs.spot.activator} | {cs.frequency_mhz_str} | {cs.spot.mode} | {cs.spot.band} | Score: {cs.dx_percentage} | {cs.display_location}"
            )
        )
        menu.addAction(act_copy_all)

        menu.addSeparator()

        act_filter_act = QAction(f"Filter by Activator '{cs.spot.activator}'", self)
        act_filter_act.triggered.connect(lambda: self.txt_search.setText(cs.spot.activator))
        menu.addAction(act_filter_act)

        act_filter_park = QAction(f"Filter by Park '{cs.spot.reference}'", self)
        act_filter_park.triggered.connect(lambda: self.txt_search.setText(cs.spot.reference))
        menu.addAction(act_filter_park)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def export_table_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Table to CSV",
            os.path.expanduser("~/pota_active_comparison.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [
                    "Status",
                    "Score",
                    "Activator",
                    "Frequency",
                    "Time",
                    "Park Reference",
                    "Park Name",
                    "Location",
                    "Band",
                    "Mode",
                    "Distance & Bearing",
                    "Grid",
                    "Comments",
                ]

                writer.writerow(headers)

                for r in range(self.table.rowCount()):
                    row_vals = []
                    for c in range(self.table.columnCount()):
                        item = self.table.item(r, c)
                        row_vals.append(item.text() if item else "")
                    writer.writerow(row_vals)

            self.status_bar.showMessage(f"Exported {self.table.rowCount()} rows to {file_path}")
            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported {self.table.rowCount()} rows to:\n{file_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV:\n{e}")

    def show_header_context_menu(self, pos):
        menu = QMenu(self)
        act_autofit = QAction("Auto-fit All Column Widths", self)
        act_autofit.triggered.connect(self.table.resizeColumnsToContents)
        menu.addAction(act_autofit)

        act_reset = QAction("Reset Column Widths to Default", self)
        act_reset.triggered.connect(self.reset_column_widths)
        menu.addAction(act_reset)

        menu.addSeparator()

        act_toggle_tooltips = QAction(
            "[x] Enable Row Tooltips" if self.show_tooltips else "[ ] Enable Row Tooltips",
            self,
        )
        act_toggle_tooltips.triggered.connect(
            lambda: self.chk_tooltips.setChecked(not self.show_tooltips)
        )
        menu.addAction(act_toggle_tooltips)

        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def reset_column_widths(self):
        for col, width in enumerate(self.default_column_widths):
            self.table.setColumnWidth(col, width)

    def closeEvent(self, event):
        # Stop background timers and worker tasks
        self.refresh_timer.stop()
        if hasattr(self, "startup_lightning_timer") and self.startup_lightning_timer.isActive():
            self.startup_lightning_timer.stop()
        if hasattr(self, "status_queue_timer") and self.status_queue_timer.isActive():
            self.status_queue_timer.stop()
        if hasattr(self, "utc_clock_timer") and self.utc_clock_timer.isActive():
            self.utc_clock_timer.stop()
        if hasattr(self, "utc_rollover_timer") and self.utc_rollover_timer.isActive():
            self.utc_rollover_timer.stop()
        for w in list(self._active_workers):
            if hasattr(w, "signals"):
                try:
                    w.signals.finished.disconnect()
                except Exception:
                    pass
                try:
                    w.signals.error.disconnect()
                except Exception:
                    pass
        self._active_workers.clear()
        self.threadpool.waitForDone(1500)

        # Sync current input text before saving QSettings
        if hasattr(self, 'txt_my_call'):
            self.my_call = self.txt_my_call.text().strip().upper()
        if hasattr(self, 'txt_grid') and self.txt_grid.text().strip():
            self.home_grid = self.txt_grid.text().strip().upper()

        # Save table header state, window geometry, callsign, home grid, tooltip toggle, station, P2P, and filter menu settings
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("table_header_state", self.table.horizontalHeader().saveState())
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("my_call", self.my_call)
        settings.setValue("home_grid", self.home_grid)

        settings.setValue("show_tooltips", self.show_tooltips)
        settings.setValue("low_memory_mode", self.low_memory_mode)
        settings.setValue("p2p_mode", self.p2p_mode)
        settings.setValue("p2p_my_park", self.p2p_my_park)
        settings.setValue("tx_power", self.tx_power)
        settings.setValue("antenna_type", self.antenna_type)
        settings.setValue("csv_path", self.csv_path)
        settings.setValue("filter_status_idx", self.combo_status.currentIndex())
        settings.setValue("filter_dx_idx", self.combo_dx.currentIndex())
        settings.setValue("filter_band", self.combo_band.currentText())
        settings.setValue("filter_mode", self.combo_mode.currentText())
        settings.setValue("refresh_interval_idx", self.combo_refresh.currentIndex())
        settings.setValue("map_render_mode", getattr(self, 'map_render_mode', MAP_RENDER_AUTO))
        if getattr(self, 'map_server', None):
            self.map_server.stop()
        if getattr(self, 'map_window', None):
            self.map_window.close()
        super().closeEvent(event)


def main():
    # Safe Chromium / QtWebEngine configuration across platforms
    if "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ:
        if is_chromebook_crostini():
            # Chromebook Crostini GPU drivers (virgl) fail with dma_buf compositor
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox"
        elif sys.platform.startswith('linux'):
            # On standard Linux (especially AppImages), forcing WebGL crashes GLX. Allow Chromium to safely fallback.
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"
        else:
            # Safe defaults enabling WebGL without forcing GLX aborts on Windows/macOS
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--enable-webgl --ignore-gpu-blocklist"

    app = QApplication(sys.argv)
    app.setApplicationName("POTA Prop")
    
    icon_path = get_resource_path("pota_prop.png")
    app_icon = QIcon(icon_path)
    app.setWindowIcon(app_icon)
    app.setDesktopFileName("pota-prop.desktop")
    
    app.setStyleSheet(DARK_STYLESHEET)
    window = POTAPropApp()
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
