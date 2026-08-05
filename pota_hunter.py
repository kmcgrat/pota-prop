#!/usr/bin/env python3
"""
POTA Hunter
A modern desktop GUI application for amateur radio operators hunting Parks on the Air.
Compares your hunted parks history against live POTA active spots.
"""

import csv
import os
import sys
import time
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional

APP_VERSION = "26.8.5"


from PyQt6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
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
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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
)
from lightning_engine import (
    LightningActivityLevel,
    RegionalLightningSummary,
    fetch_regional_lightning_summary,
    reset_lightning_engine_location,
)
from propagation_engine import (
    ANTENNA_PRESETS,
    DEFAULT_ANTENNA_TYPE,
    DEFAULT_HOME_GRID,
    DEFAULT_TX_POWER_WATTS,
    POWER_PRESETS,
    CallsignLocation,
    CallsignResolver,
    PropagationResult,
    SolarWeather,
    SpotEvidence,
    fetch_live_solar_weather,
    is_self_spot,
    maidenhead_to_latlon,
    resolve_antenna_preset,
)


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #161b22;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
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
"""


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



class FetchSpotsWorkerSignals(QObject):
    finished = pyqtSignal(list, object, object)
    error = pyqtSignal(str)


class FetchSpotsWorker(QRunnable):
    """Background worker to fetch live spots, NOAA solar weather, and regional lightning without freezing the UI."""

    def __init__(self, home_lat: float = 38.3125, home_lon: float = -81.7083):
        super().__init__()
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.signals = FetchSpotsWorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self):
        try:
            spots = fetch_active_spots(timeout=10)
            solar = fetch_live_solar_weather(timeout=5)
            lightning = fetch_regional_lightning_summary(self.home_lat, self.home_lon, timeout=5)
            self.signals.finished.emit(spots, solar, lightning)
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
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


class StatCard(QFrame):
    """Modern dashboard stat metric card."""

    def __init__(
        self,
        title: str,
        value: str = "0",
        accent_color: str = "#58a6ff",
        parent=None,
    ):
        super().__init__(parent)
        self.accent_color = accent_color
        self.setFrameShape(QFrame.Shape.StyledPanel)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 700;")
        layout.addWidget(self.lbl_title)

        self.lbl_value = QLabel(value)
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_size = "14px" if len(value) > 14 else "18px"
        self.lbl_value.setStyleSheet(
            f"color: {accent_color}; font-size: {font_size}; font-weight: 800;"
        )
        layout.addWidget(self.lbl_value)

    def set_value(self, val: str):
        val_str = str(val)
        self.lbl_value.setText(val_str)
        font_size = "14px" if len(val_str) > 14 else "18px"
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
        font_size = "14px" if len(self.lbl_value.text()) > 14 else "18px"
        self.lbl_value.setStyleSheet(
            f"color: {accent_color}; font-size: {font_size}; font-weight: 800;"
        )


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
        self.resize(880, 560)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 1. Header Banner
        header = QFrame()
        header.setStyleSheet(
            "background-color: #1c2128; border: 1px solid #30363d; border-radius: 8px; padding: 10px;"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)

        # Activator & Park details
        info_vbox = QVBoxLayout()
        lbl_act = QLabel(
            f"<span style='color:#58a6ff; font-size:18px; font-weight:800;'>{cs.spot.activator}</span> "
            f"<span style='color:#8b949e;'>at</span> "
            f"<span style='color:#f1e05a; font-size:16px; font-weight:700;'>{cs.spot.reference}</span>"
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
            f"background-color: #161b22; border: 2px solid {prob_color}; border-radius: 8px; padding: 6px 16px;"
        )
        prob_vbox = QVBoxLayout(prob_card)
        prob_vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_p_title = QLabel("QSO SCORE")
        lbl_p_title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold;")
        score_text = f"{prob} !" if prob >= 99 else f"{prob}"
        lbl_p_val = QLabel(score_text)
        lbl_p_val.setStyleSheet(f"color: {prob_color}; font-size: 26px; font-weight: 900;")
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
        s_layout.addWidget(lbl_phys)

        # Empirical Evidence details
        ev = cs.spot_evidence
        if ev:
            local_spotter_names = [
                (
                    f"{s.callsign} ({s.state or ''} {s.grid or ''}, {int(s.distance_miles)} mi away)"
                    if s.distance_miles
                    else f"{s.callsign} ({s.state or ''})"
                )
                for s in ev.local_spotters
            ]
            op_land_tag = ev.op_land_desc if (ev and ev.op_land_desc) else "Local Area"
            local_str = (
                ", ".join(local_spotter_names)
                if local_spotter_names
                else f"None detected in immediate {op_land_tag} area"
            )
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

            lbl_ev = QLabel(
                f"<b>Local Spotters ({op_land_tag}):</b> <span style='color:#79c0ff;'>{local_str}</span><br>"
                f"<b>Reports & Mentions:</b> {state_str} | <b>Signal Reports:</b> {sig_str} | <b>Impact:</b> {boost_text}"
            )
            s_layout.addWidget(lbl_ev)
        else:
            s_layout.addWidget(QLabel("<i>No empirical spot stream history available for this station.</i>"))

        layout.addWidget(summary_box)

        # 3. Respot Stream Table
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


class AboutDialog(QDialog):
    """
    Modal dialog displaying software version, application overview, key features,
    and helpful web links for POTA Hunter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About POTA Hunter")
        self.setFixedSize(580, 530)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # App Header (No boxes or frame containers)
        app_name = QLabel("POTA Hunter")
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
            "POTA Hunter compares your historical hunted parks log against live active spots "
            "from pota.app in real-time. It provides propagation estimations, multi-layer ionospheric "
            "modeling (1E–4F2), skip-zone cutoff calculations, and regional 750-mile "
            "Blitzortung.org lightning QRN monitoring."
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
            "• Multi-layer ionospheric modeling (E, F1, F2) & multi-hop ray tracing",
            "• Skip-zone cutoff calculations based on operating frequency and distance",
            "• 750-mile Blitzortung.org lightning stream & ITU-R P.372 QRN noise calculations",
            "• Station link budget calculations with transmitter power (Watts) & antenna patterns",
            "• Auto-comparison with local hunted CSV log, P2P portable mode & worked status tracking",
        ]

        for f in features:
            lbl = QLabel(f)
            lbl.setStyleSheet("color: #8b949e; font-size: 12px; border: none; background: transparent;")
            features_layout.addWidget(lbl)

        layout.addWidget(features_box)

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

        layout.addLayout(btn_layout)


class DocumentationDialog(QDialog):
    """
    Comprehensive User Guide and Documentation modal dialog for POTA Hunter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("POTA Hunter - User Guide & Reference")
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

        lbl_title = QLabel("POTA Hunter User Guide & Reference")
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

        <h2 style="color: #58a6ff; margin-top: 14px;">1. Getting Started: Downloading & Loading Your Hunter Log</h2>
        <p><b>POTA Hunter</b> is a desktop application designed for amateur radio operators hunting Parks on the Air. It compares live activator spots from <a href="https://pota.app" style="color: #7ee787;">pota.app</a> against your historical hunted CSV log, estimating contact probability using ionospheric ray tracing, live space weather, and regional atmospheric lightning noise (QRN).</p>
        
        <h3 style="color: #7ee787;">Step-by-Step Initial Setup:</h3>
        <ol>
            <li><b>Download Your Log from pota.app:</b> Open <a href="https://pota.app" style="color: #7ee787;">pota.app</a> in your web browser and sign in. Navigate to <b>Profile</b> &rarr; <b>My Stats</b>, scroll down to the <b>Hunted Parks</b> table, and click <b>Export CSV</b>. This saves <code>hunter_parks.csv</code> to your Downloads folder.</li>
            <li><b>Important Download Tip (Browser File Duplicates):</b> When you download a new export, web browsers automatically append <code>(1)</code> or <code>(2)</code> to the filename if an older file exists (e.g., <code>hunter_parks (1).csv</code>). Always delete or overwrite your old <code>hunter_parks.csv</code> in your Downloads folder before downloading a new one, or click <b>Browse CSV File</b> in POTA Hunter to select the exact file!</li>
            <li><b>Load Into POTA Hunter:</b> Click <i>File &rarr; Reload Hunter Log CSV</i> or use the <b>Browse CSV File</b> button to select your file. The app compares active spots against your log, highlighting <b>NEW (unhunted)</b> parks versus parks you have already worked.</li>
            <li><b>Operator Callsign:</b> Enter your callsign in the <b>My Call</b> field. The app automatically looks up your home Maidenhead grid locator from online databases.</li>
            <li><b>Home Grid:</b> Enter your Maidenhead Grid Locator (e.g. <code>EM98dh</code>) to establish your exact QTH reference point for distance, bearing, and propagation calculations.</li>
        </ol>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">2. Filtering, Searching, Station Setup & Portable Operation</h2>
        <ul>
            <li><b>Multi-Criteria Filters:</b> Filter spots by Status (<i>All</i>, <i>New</i>, <i>Hunted</i>, <i>Worked</i>, <i>P2P</i>), Score Threshold (<i>All</i>, <i>&ge;25</i>, <i>&ge;50</i>, <i>&ge;75</i>, <i>&ge;99</i>), Band, and Mode.</li>
            <li><b>Instant Search:</b> Type any callsign, park reference, park name, state, grid, or comment keyword into the search box for real-time table filtering.</li>
            <li><b>Transmitter Power (Watts):</b> Select your rig's output power (QRP 5W, 100W, 500W, or 1500W Legal Limit). The link budget calculation adjusts transmitter output in dBW and expected receiver SNR accordingly.</li>
            <li><b>Dynamic Antenna Elevation Modeling:</b> Choose your antenna setup (Dipole, End-Fed Half Wave, Vertical, Magnetic Loop, Random Wire, or 3-Element Beam). POTA Hunter calculates the take-off launch angle (&Delta;) from the ray-tracer and computes the antenna's gain G(&Delta;, f) at that elevation angle:
                <ul>
                    <li><b>Beam / Yagi / Hexbeam:</b> Provides low-angle DX gain (&Delta; 5°–20°) for long-distance multi-hop paths.</li>
                    <li><b>Vertical (1/4-wave / 5/8-wave):</b> Low takeoff lobe (+4.5 to +5.5 dBi at &Delta; 8°–22°), with reduced response at steep NVIS angles (&Delta; &gt; 45°).</li>
                    <li><b>Dipole (1/2-wave @ 0.5&lambda;):</b> Broad elevation pattern at high NVIS angles (&Delta; 40°–65°), with standard response at DX angles.</li>
                    <li><b>End-Fed Half Wave (EFHW):</b> Multi-band half-wave performance with realistic unun transformer loss.</li>
                    <li><b>Magnetic Loop:</b> Compact QRP loop pattern with ground efficiency adjustments.</li>
                    <li><b>Random Wire / Compromised:</b> Emulates field wire antennas with unun transformer and counterpoise ground loss factors.</li>
                </ul>
            </li>
            <li><b>Park-to-Park (P2P) Mode:</b> Operating portable from a park? Check the <b>Park-to-Park (P2P)</b> checkbox and enter your current activator park reference (e.g. <code>US-1845</code>). The app resolves your park's grid and re-centers all distance, bearing, and propagation calculations from your active park grid.</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">3. Marking Contacts Off Your List & Community Spotting</h2>
        <h3 style="color: #7ee787;">How to Mark a Contact as Worked:</h3>
        <p>When you complete a QSO with an active park, you can update your session tracking:</p>
        <ul>
            <li><b>Status Cell Dropdown:</b> Click the drop-down menu in the <b>Status</b> column of the activator's row and select <b>Mark [WORKED]</b>. The row immediately turns green, and your metric counters update in real-time.</li>
            <li><b>Right-Click Menu:</b> Right-click anywhere on the row and select <b>Toggle Worked Status</b>.</li>
        </ul>

        <h3 style="color: #7ee787;">Automatic Re-Spotting Prompt:</h3>
        <p>When you mark a park as worked, POTA Hunter displays a prompt asking if you'd like to open <code>pota.app</code> to re-spot the activator. Clicking <b>Open pota.app to Spot</b> takes you straight to the park page in your browser so you can submit your spot.</p>

        <h3 style="color: #7ee787;">Community Re-Spotting:</h3>
        <p>Re-spotting updates the global POTA network, refreshing the activator's active window and providing current spot evidence for other hunters in your region.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">4. Custom Filter Presets & Quick Shortcuts</h2>
        <p>Create tailored operating views to match your equipment and preferences:</p>
        <ul>
            <li><b>Creating Presets:</b> Adjust your filters (e.g. <i>New Only</i> + <i>20m</i> + <i>CW</i> + <i>Score &ge; 50</i>). Click <b>Filter Presets</b> &rarr; <b>Save Current as Preset...</b> and give it a name (e.g., <i>"20m CW Hunt"</i>).</li>
            <li><b>Loading Presets:</b> Select your saved preset from the <b>Filter Presets</b> menu to restore your complete filtering state instantly.</li>
        </ul>
        
        <h3 style="color: #7ee787;">Keyboard Shortcuts:</h3>
        <table border="0" cellpadding="5" cellspacing="0" style="color: #c9d1d9; font-size: 13px;">
            <tr><td><b style="color: #58a6ff;">F1</b></td><td>Open About POTA Hunter window</td></tr>
            <tr><td><b style="color: #58a6ff;">F2 / Ctrl+H</b></td><td>Open this Documentation & Guide window</td></tr>
            <tr><td><b style="color: #58a6ff;">F5</b></td><td>Trigger immediate manual spot & weather refresh</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+O</b></td><td>Reload / Browse Hunter Log CSV</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+S</b></td><td>Export current table view to CSV</td></tr>
            <tr><td><b style="color: #58a6ff;">Ctrl+Q</b></td><td>Exit Application</td></tr>
        </table>

        <br />
        <h1 style="color: #7ee787; font-size: 18px; margin-top: 16px; border-bottom: 2px solid #238636; padding-bottom: 6px;">PART II: PROPAGATION MODELING & TELEMETRY GUIDE</h1>

        <h2 style="color: #58a6ff; margin-top: 14px;">5. QSO Score, Reliability (REL), and The "+" Local Verification Symbol</h2>
        <p>POTA Hunter calculates an estimated <b>QSO Score</b> (0 to 100+) for every active spot. This score estimates the likelihood of completing a QSO with that activator based on ray-hop geometry, link budget SNR, ionospheric absorption, regional lightning QRN noise, and real-time spotter reports.</p>
        
        <h3 style="color: #7ee787;">What Does the "+" Symbol Mean (e.g. <code>85+</code>)?</h3>
        <p>The <b><code>+</code> symbol</b> next to a score indicates <b>Local Spot Verification</b>. When independent third-party spotters in your geographical region (e.g., nearby call areas or local spotters) re-spot an activator, it indicates that the signal is actively propagating into your area. The engine adds a score adjustment and marks the spotter comment with a green <code>+</code> tag.</p>
        <p><b>Activator Self-Spot Protection:</b> Activator self-spots (where the spotter callsign matches the activator) are not counted as third-party local spotters, preventing self-spots from triggering a <code>+</code> badge. Self-spot comments are still parsed for frequency changes and QRT notifications.</p>

        <h3 style="color: #7ee787;">Diagnostic Mouseover Tooltips:</h3>
        <p>Hover your mouse cursor over any <b>Score</b> badge or table row to view a detailed popup containing path diagnostics: ray mode (e.g., <i>1F2</i>, <i>2F2</i>), launch takeoff angle, dynamic antenna gain at that takeoff angle, estimated path loss in dB, predicted receiver SNR in dB, estimated Maximum Usable Frequency (MUF), Grayline status, and regional lightning QRN surges.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">6. Multi-Layer Ionospheric Profiling & Multi-Hop Ray Tracing</h2>
        <p>POTA Hunter models how radio waves refract through the ionosphere using standard ionospheric layers and ray geometry:</p>
        
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

        <h2 style="color: #58a6ff;">7. Skip-Zone & Oblique Critical Frequency Calculations</h2>
        <p>Ionospheric propagation depends on whether operating frequencies exceed the oblique critical frequency for a given path distance:</p>

        <h3 style="color: #7ee787;">How Skip-Zone Conditions Occur:</h3>
        <ul>
            <li><b>Oblique Reflection Condition:</b> For a radio wave to refract back to Earth, the operating frequency must be less than or equal to the oblique critical frequency: <code>f &le; foF2 × sec(&phi;<sub>inc</sub>)</code>.</li>
            <li><b>Ionospheric Penetration (Skip Zone):</b> On short-distance paths (e.g. 200–500 miles), the radio wave strikes the F2 layer at a steep angle (&phi;<sub>inc</sub> is small, sec(&phi;<sub>inc</sub>) &approx; 1.1–1.3). If foF2 is low, high frequencies penetrate through the ionosphere rather than reflecting.</li>
            <li><b>Nighttime foF2 Decay:</b> At night, reduced solar radiation causes foF2 to drop to 3–5 MHz, leading higher HF bands to penetrate.</li>
            <li><b>Engine Action:</b> When penetration occurs, the engine sets the status to <code>Closed (Skip Zone / Penetration: Freq > Oblique MUF)</code> and adjusts the probability score accordingly.</li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">8. Regional Lightning & Atmospheric Noise Engine (Blitzortung Telemetry & QRN Modeling)</h2>
        <p>Thunderstorms and lightning static crashes (QRN) elevate the receiver noise floor. POTA Hunter monitors regional lightning activity and estimates noise impact:</p>

        <h3 style="color: #7ee787;">1. Regional Lightning Monitoring (via Blitzortung.org):</h3>
        <ul>
            <li><b>Live WebSocket Streaming:</b> POTA Hunter connects to the <a href="https://www.blitzortung.org" style="color: #7ee787;">Blitzortung.org</a> community lightning detection network via a background streaming WebSocket.</li>
            <li><b>750-Mile (1,200 km) Regional Monitoring Radius:</b> The engine processes lightning strokes occurring within a 750-mile radius centered on your home QTH (or your active P2P activator park).</li>
            <li><b>60-Minute Sliding Window & Time-Decay Weighting:</b> Incoming strikes are buffered across a 60-minute window with age-based weighting:
                <ul>
                    <li><b>0–10 minutes old:</b> 100% weight (1.0) — Active, immediate local storm activity</li>
                    <li><b>10–20 minutes old:</b> 70% weight (0.70) — Recent storm activity</li>
                    <li><b>20–30 minutes old:</b> 45% weight (0.45) — Mature / drifting cells</li>
                    <li><b>30–60 minutes old:</b> 20% weight (0.20) — Residual activity</li>
                </ul>
            </li>
            <li><b>Spatial Density & Storm Cell Clustering:</b> Strikes are grouped spatially by distance and bearing to compute strike rates (<code>strikes/min</code> and <code>strikes/hr</code>).</li>
            <li><b>Automatic Location & Callsign Reset:</b> When you change your callsign or Maidenhead grid, the lightning engine resets its buffer and re-centers its 750-mile monitoring radius for your new QTH.</li>
        </ul>

        <h3 style="color: #7ee787;">2. How Lightning QRN Noise Surges and Activity Levels are Calculated:</h3>
        <ul>
            <li><b>Inverse-Distance Decay:</b> Electromagnetic pulses (sferics) propagate through the Earth-ionosphere waveguide; noise surge intensity scales with distance following <code>1 / d^1.8</code>.</li>
            <li><b>Frequency-Dependent QRN Susceptibility:</b> Lightning electromagnetic energy is concentrated in the low-frequency spectrum and decreases on higher bands following <code>1 / f^1.3</code>:
                <ul>
                    <li><b>160m:</b> Higher noise surge impact</li>
                    <li><b>80m:</b> Substantial noise surge impact</li>
                    <li><b>40m:</b> Moderate noise surge impact</li>
                    <li><b>20m:</b> Minor noise floor increase</li>
                    <li><b>15m / 10m:</b> Minimal impact</li>
                </ul>
            </li>
            <li><b>Noise Floor & Link Budget Impact:</b> The calculated QRN surge (&Delta;F<sub>QRN</sub> in dB) is factored into the ITU-R P.372 atmospheric noise floor calculation.</li>
            <li><b>1-to-10 Lightning Scale:</b>
                <ul>
                    <li><b>Level 1–3 (Clear / Low):</b> No storms or distant sferics (300–750 mi). Low noise floor.</li>
                    <li><b>Level 4–6 (Moderate / High Regional):</b> Active thunderstorms within 85–300 mi. Elevated QRN (+8 to +16 dB).</li>
                    <li><b>Level 7–8 (Approaching / Nearby Storms):</b> Lightning within 30–100 mi. Heavy static crashes.</li>
                    <li><b>Level 9–10 (⚠️ DISCONNECT ADVISORY / DANGER):</b> Lightning within 15–30 miles (Level 9: Very Close Proximity) or immediate vicinity &lt; 15 miles (Level 10: Immediate Hazard). <b>Consider disconnecting coax feedlines, rotor cables, and AC power to protect station equipment from induced voltage surges and direct strikes.</b></li>
                </ul>
            </li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">9. Link Budget, Antenna Elevation Gain & Signal-to-Noise Ratio (SNR)</h2>
        <p>POTA Hunter calculates an RF link budget for every active spot using standard transmission equations:</p>

        <h3 style="color: #7ee787;">1. Path Loss Formulation (L<sub>b</sub>):</h3>
        <ul>
            <li><b>Free-Space Basic Transmission Loss (L<sub>bf</sub>):</b> <code>L_bf = 32.45 + 20 log10(f_MHz) + 20 log10(d_slant_km)</code></li>
            <li><b>ITU-R P.533 Ionospheric Absorption (L<sub>a</sub>):</b> Non-deviative D-layer absorption evaluating spherical obliquity factor <code>sec(&phi;_D)</code> through the 75 km layer: <code>L_a = 2 × N_hops × A_D × sec(&phi;_D)</code>, where <code>A_D</code> scales with solar zenith angle and gyrofrequency (<code>f + 1.4 MHz</code>).</li>
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
            <li><b>Total Receiver Noise Power (N<sub>dBW</sub>):</b> <code>N = -204 + 10 log10(BW_Hz) + F_a + &Delta;F_QRN</code>, where <code>F_a</code> is the ITU-R P.372 atmospheric/man-made noise figure and <code>&Delta;F_QRN</code> is the regional lightning surge.</li>
            <li><b>Predicted SNR:</b> <code>SNR_dB = S_dBW - N_dBW</code>.</li>
            <li><b>Circuit Reliability (REL):</b> Modeled via log-normal error distribution:
                <br /><code>REL = 0.5 × [1 + erf((SNR - SNR_req) / (sqrt(2) × &sigma;_fading))] × 100%</code></li>
        </ul>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">10. Space Weather Telemetry: NOAA Solar Flares, PSKReporter & QRT Detection</h2>
        <h3 style="color: #7ee787;">Geomagnetic Indices: Planetary K-Index vs. Planetary A-Index:</h3>
        <ul>
            <li><b>K-Index (0 to 9, 3-Hour Metric):</b> Measures geomagnetic activity. K &le; 2 is quiet; K &ge; 4 indicates disturbed conditions.</li>
            <li><b>A-Index (0 to 400, 24-Hour Cumulative Metric):</b> High A-index (A &ge; 25) reflects cumulative storminess that may reduce F2-layer critical frequencies.</li>
        </ul>

        <h3 style="color: #7ee787;">NOAA GOES Satellite Solar Flares & Radio Blackouts (R1 to R5):</h3>
        <p>POTA Hunter monitors real-time 0.1–0.8nm X-ray flux from NOAA GOES satellites:</p>
        <ul>
            <li><b>M-Class Flares (R1/R2 Blackout):</b> Applies a <b>-15 to -25 point adjustment</b> on daylight HF paths due to increased D-layer absorption.</li>
            <li><b>X-Class Flares (R3/R4/R5 Severe Blackout):</b> Applies a <b>-40 to -50 point adjustment</b> to reflect radio blackout conditions.</li>
        </ul>

        <h3 style="color: #7ee787;">Automated QRT Detection:</h3>
        <p>When spotters post comments indicating an activator has shut down (e.g. <i>QRT</i>, <i>going QRT</i>, <i>off air</i>, <i>73 QRT</i>), the score is set to <b>0</b> and the status is marked as <b>Activator QRT (Off the air)</b>.</p>

        <h3 style="color: #7ee787;">PSKReporter & WSPR Decodes:</h3>
        <p>Spot comments referencing live digital decodes (e.g. <i>FT8 decode on PSKReporter in EM98</i>) apply a <b>+15 point PSKReporter Live Opening Boost</b>.</p>

        <hr style="border: 1px solid #30363d;" />

        <h2 style="color: #58a6ff;">11. Tooltip Propagation Outcomes & Telemetry Reference Guide</h2>
        <p>When you hover your mouse over any <b>Score</b> badge or row in the table, POTA Hunter displays a diagnostic popup. Below is a reference of the telemetry lines:</p>
        
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




class POTAHunterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POTA Hunter")

        self.resize(1340, 850)
        self.setMinimumSize(980, 600)

        self.threadpool = QThreadPool()
        self._active_workers: List[QRunnable] = []
        self.csv_path = DEFAULT_HUNTER_CSV_PATH
        self.hunted_parks: Dict[str, HuntedPark] = {}
        self.active_spots: List[ActiveSpot] = []
        self.compared_spots: List[ComparedSpot] = []

        # Settings, Operator Call, Grid, Station, P2P Mode, and Filters
        settings = QSettings("POTA", "HunterComparator")
        self.csv_path = str(settings.value("csv_path", DEFAULT_HUNTER_CSV_PATH)).strip() or DEFAULT_HUNTER_CSV_PATH
        self.my_call = str(settings.value("my_call", "")).strip().upper()
        self.home_grid = str(settings.value("home_grid", DEFAULT_HOME_GRID)).strip().upper() or DEFAULT_HOME_GRID
        self.current_grid = self.home_grid
        self.show_tooltips = settings.value("show_tooltips", True, type=bool)
        self.p2p_mode = settings.value("p2p_mode", False, type=bool)
        self.p2p_my_park = str(settings.value("p2p_my_park", "")).strip().upper()
        self.tx_power = float(settings.value("tx_power", DEFAULT_TX_POWER_WATTS))
        self.antenna_type = str(settings.value("antenna_type", DEFAULT_ANTENNA_TYPE)).strip()
        self.filter_status_idx = 0  # Always start with 'All' filter
        self.filter_dx_idx = settings.value("filter_dx_idx", 0, type=int)
        self.filter_band = str(settings.value("filter_band", "All Bands")).strip()
        self.filter_mode = str(settings.value("filter_mode", "All Modes")).strip()
        self.refresh_interval_idx = settings.value("refresh_interval_idx", 2, type=int)
        saved_worked = settings.value("manually_worked_parks", [])
        if isinstance(saved_worked, list):
            self.manually_worked_parks = set(str(x).strip().upper() for x in saved_worked if x)
        else:
            self.manually_worked_parks = set()
        self.solar_weather = SolarWeather()
        self.lightning_summary: Optional[RegionalLightningSummary] = None
        self._is_fetching = False

        # Auto refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.fetch_spots)

        self.init_ui()

        # Explicitly initialize auto-refresh timer with saved combo interval
        self.on_refresh_interval_changed(self.combo_refresh.currentIndex())

        # Restore saved window geometry if present
        saved_geom = settings.value("window_geometry")
        if saved_geom:
            self.restoreGeometry(saved_geom)

        self.load_initial_csv()
        self.recompute_comparisons()
        self.fetch_spots()

    def init_ui(self):
        self.setStyleSheet(DARK_STYLESHEET)
        self.create_menu_bar()

        # Status Bar (initialize early so signal callbacks during UI creation can post messages)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

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

        view_menu.addSeparator()

        autofit_action = QAction("Auto-fit Column Widths", self)
        autofit_action.triggered.connect(self.autofit_columns)
        view_menu.addAction(autofit_action)

        reset_cols_action = QAction("Reset Column Layout to Default", self)
        reset_cols_action.triggered.connect(self.reset_column_widths)
        view_menu.addAction(reset_cols_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")

        docs_action = QAction("&Documentation", self)
        docs_action.setShortcut(QKeySequence("F2"))
        docs_action.triggered.connect(self.show_docs_dialog)
        help_menu.addAction(docs_action)


        help_menu.addSeparator()

        about_action = QAction("&About POTA Hunter", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        pota_web_action = QAction("Visit POTA.app Website", self)
        pota_web_action.triggered.connect(lambda: webbrowser.open("https://pota.app"))
        help_menu.addAction(pota_web_action)


    def autofit_columns(self):
        if hasattr(self, 'table') and self.table:
            self.table.resizeColumnsToContents()

    def show_docs_dialog(self):
        dlg = DocumentationDialog(self)
        dlg.exec()

    def show_about_dialog(self):
        dlg = AboutDialog(self)
        dlg.exec()


    def create_top_bar(self) -> QWidget:

        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # App Title
        lbl_app = QLabel("POTA Hunter")
        lbl_app.setStyleSheet("color: #f0f6fc; font-size: 16px; font-weight: bold;")
        layout.addWidget(lbl_app)


        layout.addSpacing(10)

        # Operator Callsign Input
        lbl_call = QLabel("My Call:")
        lbl_call.setStyleSheet("color: #79c0ff; font-weight: bold;")
        layout.addWidget(lbl_call)

        self.txt_my_call = QLineEdit(self.my_call)
        self.txt_my_call.setPlaceholderText("e.g. W8XYZ")
        self.txt_my_call.setMaxLength(10)
        self.txt_my_call.setFixedWidth(75)
        self.txt_my_call.setToolTip("Your amateur radio callsign (automatically looks up your QTH grid)")
        self.txt_my_call.returnPressed.connect(self.on_my_call_changed)
        self.txt_my_call.editingFinished.connect(self.on_my_call_changed)
        layout.addWidget(self.txt_my_call)

        layout.addSpacing(4)

        # Single Unified Grid Locator Input
        lbl_grid = QLabel("Grid:")
        lbl_grid.setStyleSheet("color: #58a6ff; font-weight: bold;")
        layout.addWidget(lbl_grid)

        self.txt_grid = QLineEdit(self.current_grid)
        self.txt_grid.setPlaceholderText("e.g. EM98dh")
        self.txt_grid.setMaxLength(8)
        self.txt_grid.setFixedWidth(75)
        self.txt_grid.setToolTip(
            "Operating Maidenhead Grid Locator (defaults to callsign QTH, or auto-updates to park grid in P2P mode)"
        )
        self.txt_grid.returnPressed.connect(self.on_grid_changed)
        self.txt_grid.editingFinished.connect(self.on_grid_changed)
        layout.addWidget(self.txt_grid)

        btn_set_grid = QPushButton("Set")
        btn_set_grid.setToolTip("Apply and recalculate all distances, bearings, and propagation for this Grid")
        btn_set_grid.clicked.connect(self.on_grid_changed)
        layout.addWidget(btn_set_grid)

        layout.addSpacing(6)

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

        # CSV Selector
        lbl_csv = QLabel("Hunter CSV:")
        lbl_csv.setStyleSheet("color: #c9d1d9; font-weight: 600;")
        layout.addWidget(lbl_csv)

        self.txt_csv_path = QLineEdit(self.csv_path)
        self.txt_csv_path.setPlaceholderText("Select hunter_parks.csv...")
        self.txt_csv_path.setMinimumWidth(200)
        layout.addWidget(self.txt_csv_path)

        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_csv_file)
        layout.addWidget(btn_browse)

        btn_reload_csv = QPushButton("Reload Log")
        btn_reload_csv.clicked.connect(self.reload_csv)
        layout.addWidget(btn_reload_csv)

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

        self.card_new = StatCard("Unhunted (New)", "0", "#f1e05a")
        self.card_hunted = StatCard("Already Hunted", "0", "#2ea043")
        self.card_active = StatCard("Active Spots", "0", "#58a6ff")
        self.card_unique_parks = StatCard("Unique Active Parks", "0", "#bc8cff")
        self.card_total_hunted = StatCard("Total in Log", "0", "#8b949e")
        self.card_solar = StatCard("Space Weather", "SFI: -- | A: -- | K: -- | Flare: --", "#388bfd")
        self.card_solar.setToolTip(self.solar_weather.format_tooltip_html())
        self.card_lightning = StatCard("Lightning", "1", "#2ea043")

        layout.addWidget(self.card_new, stretch=2)
        layout.addWidget(self.card_hunted, stretch=2)
        layout.addWidget(self.card_active, stretch=2)
        layout.addWidget(self.card_unique_parks, stretch=2)
        layout.addWidget(self.card_total_hunted, stretch=2)
        layout.addWidget(self.card_solar, stretch=5)
        layout.addWidget(self.card_lightning, stretch=2)

        return panel

    def create_filter_box(self) -> QGroupBox:
        box = QGroupBox("Filter & Search Active Spots")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

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
        self.combo_mode.addItems(["All", "CW", "SSB", "FT8", "FT4", "FM", "AM", "Digital"])
        if self.filter_mode and self.combo_mode.findText(self.filter_mode) < 0:
            self.combo_mode.addItem(self.filter_mode)
        mode_idx = self.combo_mode.findText(self.filter_mode)
        if mode_idx >= 0:
            self.combo_mode.setCurrentIndex(mode_idx)
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

        return box

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

        self.btn_open_qrz = QPushButton("QRZ Callsign")
        self.btn_open_qrz.setEnabled(False)
        self.btn_open_qrz.clicked.connect(self.open_selected_qrz_web)
        layout.addWidget(self.btn_open_qrz)

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
        self.csv_path = self.txt_csv_path.text().strip()
        if os.path.exists(self.csv_path):
            self.hunted_parks = load_hunter_csv(self.csv_path)
            total_hunted = len(self.hunted_parks)
            total_qsos = sum(p.qsos for p in self.hunted_parks.values())
            self.card_total_hunted.set_value(f"{total_hunted:,}")
            self.status_bar.showMessage(
                f"Loaded {total_hunted:,} hunted parks ({total_qsos:,} QSOs) from {self.csv_path}"
            )
            # Check age of CSV log file (warn if older than 24 hours)
            try:
                mtime = os.path.getmtime(self.csv_path)
                age_seconds = time.time() - mtime
                age_hours = age_seconds / 3600.0
                if age_hours > 24.0 and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                    QTimer.singleShot(200, lambda: self.show_outdated_csv_dialog(age_hours, mtime))
            except Exception as e:
                logger.debug("Failed to check CSV file age: %s", e)
        else:
            self.card_total_hunted.set_value("0")
            self.status_bar.showMessage(
                f"CSV not found at {self.csv_path}. Please browse and select your hunter export."
            )
            # Display interactive alert popup with download guidance if not in headless test mode
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                QTimer.singleShot(150, self.show_missing_csv_dialog)

    def show_outdated_csv_dialog(self, age_hours: float, mtime: float):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Hunted Parks Log Update Recommended")

        if age_hours >= 48.0:
            age_days = age_hours / 24.0
            age_str = f"{age_days:.1f} days"
        else:
            age_str = f"{int(round(age_hours))} hours"

        mtime_dt = datetime.fromtimestamp(mtime)
        mtime_str = mtime_dt.strftime("%Y-%m-%d %H:%M")

        msg_box.setText(f"<b>Hunted Parks Log (hunter_parks.csv) is {age_str} Old</b>")
        msg_box.setInformativeText(
            f"Your hunted parks log was last exported on <b>{mtime_str}</b> ({age_str} ago):<br>"
            f"<code>{self.csv_path}</code><br><br>"
            "If you have made new POTA contacts since then, your log may not reflect recent hunts. "
            "To ensure new activator spots are accurately marked as <b>NEW</b> vs. <b>ALREADY HUNTED</b>, "
            "it is recommended to download a fresh log export:<br><br>"
            "<b>POTA.app Download Workflow:</b><br>"
            "1. Log into <b><a href='https://pota.app/#/user/stats'>pota.app</a></b><br>"
            "2. Navigate to <b>Profile</b> &rarr; <b>My Stats</b><br>"
            "3. Scroll down to the <b>Hunted Parks</b> table<br>"
            "4. Click <b>Export CSV</b> to download your fresh <code>hunter_parks.csv</code><br>"
            "5. Save the file and click <b>Browse CSV File...</b> (or replace your existing file)."
        )
        btn_open_web = msg_box.addButton("Open POTA.app", QMessageBox.ButtonRole.ActionRole)
        btn_browse_file = msg_box.addButton("Browse CSV File...", QMessageBox.ButtonRole.ActionRole)
        btn_continue = msg_box.addButton("Continue with Current Log", QMessageBox.ButtonRole.AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_open_web:
            webbrowser.open("https://pota.app/#/user/stats")
        elif msg_box.clickedButton() == btn_browse_file:
            self.browse_csv_file()

    def show_missing_csv_dialog(self):
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Hunted Parks Log Not Found")
        msg_box.setText("<b>Hunted Parks Log File (hunter_parks.csv) Not Found</b>")
        msg_box.setInformativeText(
            f"The hunted parks CSV log was not found at:<br><code>{self.csv_path}</code><br><br>"
            "<b>To highlight parks you've already worked vs. NEW unhunted parks:</b><br>"
            "1. Log into your account on <b><a href='https://pota.app/#/user/stats'>pota.app</a></b><br>"
            "2. Navigate to <b>Profile</b> &rarr; <b>My Stats</b><br>"
            "3. Scroll down to the <b>Hunted Parks</b> table<br>"
            "4. Click <b>Export CSV</b> to download your <code>hunter_parks.csv</code><br>"
            "5. Save the file and click <b>Browse CSV File...</b> to select it."
        )
        btn_open_web = msg_box.addButton("Open POTA.app", QMessageBox.ButtonRole.ActionRole)

        btn_browse_file = msg_box.addButton("Browse CSV File...", QMessageBox.ButtonRole.ActionRole)

        btn_continue = msg_box.addButton("Continue (All Spots = NEW)", QMessageBox.ButtonRole.AcceptRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_open_web:
            webbrowser.open("https://pota.app/#/user/stats")
        elif msg_box.clickedButton() == btn_browse_file:
            self.browse_csv_file()

    def browse_csv_file(self):
        start_dir = os.path.dirname(self.csv_path) if os.path.exists(self.csv_path) else os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select POTA Hunter CSV File",
            start_dir,
            "CSV Files (*.csv);;All Files (*)",
        )
        if file_path:
            self.txt_csv_path.setText(file_path)
            self.reload_csv()

    def reload_csv(self):
        self.csv_path = self.txt_csv_path.text().strip()
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
        self.recompute_comparisons()

    def on_my_call_changed(self):
        call = self.txt_my_call.text().strip().upper()
        self.my_call = call
        self.txt_my_call.setText(call)
        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("my_call", call)

        if not call:
            return

        # Check resolver cache first
        resolver = CallsignResolver()
        loc = resolver.lookup_user_callsign(call)
        if loc and loc.grid:
            self.home_grid = loc.grid
            settings.setValue("home_grid", loc.grid)
            if not self.p2p_mode:
                self.current_grid = loc.grid
                self.txt_grid.setText(loc.grid)
                h_lat, h_lon = maidenhead_to_latlon(loc.grid)
                if h_lat is not None and h_lon is not None:
                    self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                self.recompute_comparisons()
            name_str = f" ({loc.name})" if loc.name else ""
            self.status_bar.showMessage(
                f"Callsign {call} found -> Home Grid set to {loc.grid}{name_str}"
            )
        else:
            self.status_bar.showMessage(f"Looking up license/location for callsign {call}...")
            worker = CallsignLookupWorker(call)
            worker.signals.finished.connect(self.on_callsign_lookup_finished)
            self._run_worker(worker)

    @pyqtSlot(object)
    def on_callsign_lookup_finished(self, loc):
        if not loc or not getattr(loc, "grid", None):
            return
        if self.my_call == loc.callsign:
            clean_grid = loc.grid.strip().upper()
            self.home_grid = clean_grid
            settings = QSettings("POTA", "HunterComparator")
            settings.setValue("home_grid", clean_grid)
            if not self.p2p_mode:
                self.current_grid = clean_grid
                self.txt_grid.setText(clean_grid)
                h_lat, h_lon = maidenhead_to_latlon(clean_grid)
                if h_lat is not None and h_lon is not None:
                    self.lightning_summary = reset_lightning_engine_location(h_lat, h_lon)
                self.recompute_comparisons()
            name_str = f" ({loc.name})" if loc.name else ""
            self.status_bar.showMessage(
                f"Callsign {loc.callsign} verified -> Home Grid set to {clean_grid}{name_str}"
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
        self.recompute_comparisons()
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
        self.status_bar.showMessage("Fetching live active spots, NOAA space weather & regional lightning...")

        home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
        if home_lat is None or home_lon is None:
            home_lat, home_lon = 38.3125, -81.7083

        worker = FetchSpotsWorker(home_lat, home_lon)
        worker.signals.finished.connect(self.on_spots_fetched)
        worker.signals.error.connect(self.on_spots_error)
        self._run_worker(worker)

    def on_spots_fetched(
        self,
        spots: List[ActiveSpot],
        solar_weather: Optional[SolarWeather] = None,
        lightning_summary: Optional[RegionalLightningSummary] = None,
    ):
        self._is_fetching = False
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch Spots")
        self.active_spots = spots
        if solar_weather is not None:
            self.solar_weather = solar_weather
        if lightning_summary is not None:
            self.lightning_summary = lightning_summary
        self.recompute_comparisons()
        now_str = datetime.now().strftime("%H:%M:%S")
        light_act = self.lightning_summary.get_activity_level() if self.lightning_summary else None
        light_str = f" | Lightning: Level {light_act.level} ({light_act.label})" if light_act else ""
        self.status_bar.showMessage(
            f"Updated spots at {now_str} | {len(spots)} spots received | Solar SFI: {int(self.solar_weather.sfi)}, K: {int(self.solar_weather.k_index)} ({self.solar_weather.condition}){light_str}"
        )

    @pyqtSlot(str)
    def on_spots_error(self, err_msg: str):
        self._is_fetching = False
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch Spots")
        self.status_bar.showMessage(f"Fetch Error: {err_msg}")

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
            self.status_bar.showMessage(
                f"P2P Mode disabled -> Grid reverted to home QTH {self.home_grid}"
            )
            self.recompute_comparisons()

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
            self.recompute_comparisons()
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
            park_name = info.get("name", "")
            name_str = f" ({park_name})" if park_name else ""
            self.status_bar.showMessage(
                f"Park {norm_ref}{name_str} -> Grid set to {grid} | Recalculated P2P path & propagation"
            )
            self.recompute_comparisons()
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
                park_name = info.get("name", "")
                name_str = f" ({park_name})" if park_name else ""
                self.status_bar.showMessage(
                    f"Park {ref}{name_str} -> Grid set to {grid} | Recalculated P2P path & propagation"
                )
                self.recompute_comparisons()

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
            self.active_spots,
            self.hunted_parks,
            home_grid=self.current_grid,
            solar_weather=self.solar_weather,
            p2p_mode=self.p2p_mode,
            p2p_my_park=self.p2p_my_park,
            p2p_grid=self.current_grid,
            tx_power_watts=self.tx_power,
            antenna_type=self.antenna_type,
            op_call=self.my_call,
        )

        # Update stats
        new_count = sum(1 for c in self.compared_spots if c.is_new and c.spot.reference not in self.manually_worked_parks)
        hunted_count = sum(1 for c in self.compared_spots if not c.is_new or c.spot.reference in self.manually_worked_parks)
        unique_active_parks = len(set(c.spot.reference for c in self.compared_spots if c.spot.reference))

        if self.p2p_mode and self.p2p_my_park:
            p2p_count = sum(1 for c in self.compared_spots if c.is_p2p_eligible)
            self.card_unique_parks.set_title("P2P Available")
            self.card_unique_parks.set_value(f"{p2p_count}")
        else:
            self.card_unique_parks.set_title("Unique Active Parks")
            self.card_unique_parks.set_value(f"{unique_active_parks}")

        self.card_new.set_value(f"{new_count}")
        self.card_hunted.set_value(f"{hunted_count}")
        self.card_active.set_value(f"{len(self.compared_spots)}")

        # Update Space Weather card
        ov_lbl, ov_col, _ = self.solar_weather.get_overall_assessment()
        flare_str = self.solar_weather.xray_class if self.solar_weather.xray_class else "Normal"
        self.card_solar.set_value(
            f"SFI: {int(self.solar_weather.sfi)} | A: {int(self.solar_weather.a_index)} | K: {int(self.solar_weather.k_index)} | Flare: {flare_str}"
        )
        self.card_solar.set_accent_color(ov_col)
        self.card_solar.setToolTip(self.solar_weather.format_tooltip_html())

        # Update Lightning Activity card (1 to 10 scale)
        if self.lightning_summary is None:
            home_lat, home_lon = maidenhead_to_latlon(self.current_grid)
            if home_lat is not None and home_lon is not None:
                self.lightning_summary = fetch_regional_lightning_summary(home_lat, home_lon)
            else:
                self.lightning_summary = RegionalLightningSummary()

        act = self.lightning_summary.get_activity_level()
        self.card_lightning.set_value(str(act.level))
        self.card_lightning.set_accent_color(act.color)
        self.card_lightning.setToolTip(self.lightning_summary.format_tooltip_html())

        # Update dynamic mode filter list if new modes appeared
        current_mode = self.combo_mode.currentText()
        all_modes = set(c.spot.mode for c in self.compared_spots if c.spot.mode)
        default_modes = ["All Modes", "CW", "SSB", "FT8", "FT4", "FM", "AM", "Digital"]
        for m in sorted(all_modes):
            if m and m not in default_modes:
                default_modes.append(m)

        self.combo_mode.blockSignals(True)
        self.combo_mode.clear()
        self.combo_mode.addItems(default_modes)
        idx = self.combo_mode.findText(current_mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        else:
            self.combo_mode.setCurrentIndex(0)
        self.combo_mode.blockSignals(False)

        self.apply_filters()

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
            is_worked = cs.spot.reference in self.manually_worked_parks

            # 1. Status filter: 0=All, 1=New, 2=Hunted/Worked, 3=[WORKED] Only, 4=P2P
            if status_filter == 1 and (not cs.is_new or is_worked):
                continue
            if status_filter == 2 and (cs.is_new and not is_worked):
                continue
            if status_filter == 3 and not is_worked:
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
                if mode_filter == "Digital":
                    if cs.spot.mode not in ["FT8", "FT4", "JS8", "PSK", "RTTY", "VARAC", "DIGITAL"]:
                        continue
                elif cs.spot.mode != mode_filter:
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
        Builds a comprehensive mouseover tooltip listing nearby re-spots, spot freshness,
        and QSO feasibility. If no nearby re-spots are available, explicitly outputs 'None'.
        """
        lines = []

        # 1. Header: Station, P2P Target, & Park
        if cs.is_p2p_eligible:
            lines.append(f"P2P TARGET: {cs.spot.activator} @ {cs.spot.reference} - {cs.display_name}")
            lines.append(f"Park-to-Park Path from {cs.p2p_my_park or 'Field QTH'}")
        elif cs.is_p2p_same_park:
            lines.append(f"SAME PARK ACTIVATOR: {cs.spot.activator} @ {cs.spot.reference} - {cs.display_name}")
        else:
            lines.append(f"STATION: {cs.spot.activator} @ {cs.spot.reference} - {cs.display_name}")

        lines.append(
            f"Frequency: {cs.frequency_mhz_str} | Mode: {cs.spot.mode} | Band: {cs.spot.band}"
        )

        # 2. Spot Freshness & Decay
        exp_info = f" | Expire in ~{cs.expire_mins_remaining}m" if cs.expire_mins_remaining is not None else ""
        lines.append(f"Spot Freshness: {cs.time_ago_str} ({cs.decay_status}){exp_info}")

        # 3. RF Score & Propagation Path
        prob = cs.dx_percentage
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
        lines.append(f"RF Score: {prob} ({prob_badge}) | Distance: {dist_info}")
        lines.append(f"Propagation Path: {path_sum}")

        # 4. Nearby Re-spots Section
        ev = cs.spot_evidence
        op_land_tag = ev.op_land_desc if (ev and ev.op_land_desc) else "Local Area"
        lines.append("------------------------------------------")
        lines.append(f"Nearby Re-spots ({op_land_tag}):")

        has_nearby = False

        if ev and ev.local_spotters:
            has_nearby = True
            # Build lookup of raw respots for comments and timestamps
            respot_map = {}
            for r in cs.spot.respots or []:
                call = str(r.get("spotter") or "").strip().upper()
                if call and call not in respot_map:
                    respot_map[call] = r

            for s in ev.local_spotters:
                r = respot_map.get(s.callsign.upper(), {})
                comment = str(r.get("comments") or "").strip()
                time_raw = str(r.get("spotTime") or "")
                time_str = f" [{time_raw.replace('T', ' ')[11:16]}z]" if time_raw else ""

                loc_parts = []
                if s.state:
                    loc_parts.append(s.state)
                if s.grid:
                    loc_parts.append(s.grid)
                if s.distance_miles is not None:
                    loc_parts.append(f"{int(s.distance_miles)} mi")
                loc_desc = f" ({', '.join(loc_parts)})" if loc_parts else ""

                comment_desc = f' -- "{comment}"' if comment else ""
                lines.append(f"  * {s.callsign}{loc_desc}{time_str}{comment_desc}")

        if ev and ev.local_state_mentions:
            if not has_nearby:
                has_nearby = True
            lines.append(
                f"  * State Signal Reports in Comments: {', '.join(ev.local_state_mentions)}"
            )

        if not has_nearby:
            lines.append("  None")

        # 5. Supplemental Intelligence
        lines.append("------------------------------------------")
        if ev:
            if ev.signal_reports:
                lines.append(f"Signal Reports: {', '.join(ev.signal_reports)}")
            if ev.empirical_boost_pct != 0:
                sign = "+" if ev.empirical_boost_pct > 0 else ""
                lines.append(f"Local Evidence Boost: {sign}{ev.empirical_boost_pct}%")
            if len(cs.spot.respots) > 1:
                lines.append(f"Respots: {len(cs.spot.respots)}")

        if cs.propagation:
            p = cs.propagation
            gray_tag = " | [Grayline Active: +28%]" if p.is_grayline else ""
            muf_str = format_muf_telemetry(p)
            lines.append(
                f"Est MUF: {muf_str} | SFI {int(p.solar_info.sfi)}, A-idx {int(p.solar_info.a_index)}, K-idx {int(p.solar_info.k_index)}{gray_tag}"
            )
            if p.predicted_snr_db is not None:
                lines.append(
                    f"Ray Path: {p.ray_mode} (Takeoff {p.takeoff_angle_deg:.1f}°, Loss {p.path_loss_db:.1f} dB) | SNR: {p.predicted_snr_db:+.1f} dB"
                )
            ant_name = ANTENNA_PRESETS.get(p.antenna_type, {}).get("name", p.antenna_type)
            lines.append(
                f"Station Link: {p.tx_power_watts:.0f}W | {ant_name} ({p.antenna_gain_dbi:+.1f} dBi @ {p.takeoff_angle_deg:.1f}°) | Link Offset: {p.station_offset_db:+.1f} dB"
            )
            if p.qrn_surge_db > 0:
                lines.append(f"⚡ Lightning QRN Surge: +{p.qrn_surge_db:.1f} dB (Local Sferic Noise)")

        return "\n".join(lines)

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

            # 0: Status Badge & Dropdown Selector (with [WORKED] & P2P support)
            is_worked = cs.spot.reference in self.manually_worked_parks

            if is_worked:
                raw_auto_label = "[WORKED]"
                item_status = NumericTableWidgetItem("[WORKED]", 2.0)
                item_status.setForeground(QBrush(QColor("#3fb950")))
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
                # Exceptional: rare confluence of grayline + mode + evidence + solar
                prob_text = f"{prob} !"
                prob_color = "#FFD700"  # Gold
            elif prob >= 75:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#3fb950"  # Bright vibrant green
            elif prob >= 50:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#e3b341"  # Bright amber
            elif prob >= 25:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#db6d28"  # Orange
            elif prob > 0:
                prob_text = f"{prob} +" if has_local else f"{prob}"
                prob_color = "#8b949e"  # Gray
            else:
                prob_text = "0"
                prob_color = "#f85149"  # Red

            item_dx = NumericTableWidgetItem(prob_text, float(prob))
            item_dx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_dx.setForeground(QBrush(QColor(prob_color)))
            item_dx.setFont(QFont("", -1, QFont.Weight.Bold))
            item_dx.setToolTip(row_tooltip)

            # 2: Park Reference
            # 2: Activator
            item_call = QTableWidgetItem(cs.spot.activator)
            item_call.setFont(QFont("", -1, QFont.Weight.Bold))
            item_call.setForeground(QBrush(QColor("#d29922")))
            item_call.setToolTip(row_tooltip)

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
            if is_worked:
                combo_status.addItem("[WORKED]")
                combo_status.addItem(f"Auto ({raw_auto_label})")
                combo_status.setCurrentIndex(0)
                combo_status.setStyleSheet(
                    "QComboBox { background-color: #1b4b27; color: #3fb950; border: 1px solid #2ea043; font-weight: bold; border-radius: 4px; padding: 1px 4px; }"
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
            was_worked = is_worked

            def on_cell_status_changed(index: int, ref=target_ref, call=target_call, is_w=was_worked):
                if is_w and index == 1:
                    self.toggle_park_worked(ref, force_state=False)
                elif not is_w and index == 1:
                    self.toggle_park_worked(ref, force_state=True, activator_call=call)

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

    def prompt_spot_on_pota(self, park_ref: str, activator_call: str = ""):

        """
        Prompt dialog encouraging the hunter to open pota.app to re-spot the activator
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
        dlg.setWindowTitle("Spot Activator on pota.app")
        dlg.setFixedSize(480, 220)
        dlg.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        lbl_title = QLabel("Re-Spot Activator on pota.app?")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(lbl_title)

        msg_label = QLabel(
            f"Congratulations on working park {park_ref}{call_str}!\n\n"
            "Would you like to open pota.app to re-spot this activator? "
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

        btn_spot = QPushButton("Open pota.app to Spot")
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
            webbrowser.open(f"https://pota.app/#/park/{park_ref}")
            dlg.accept()

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

    def toggle_park_worked(self, park_ref: str, force_state: Optional[bool] = None, activator_call: str = ""):
        ref = normalize_ref(park_ref)
        if not ref:
            return
        is_now_worked = False
        if force_state is True:
            self.manually_worked_parks.add(ref)
            is_now_worked = True
        elif force_state is False:
            self.manually_worked_parks.discard(ref)
        else:
            if ref in self.manually_worked_parks:
                self.manually_worked_parks.discard(ref)
            else:
                self.manually_worked_parks.add(ref)
                is_now_worked = True

        settings = QSettings("POTA", "HunterComparator")
        settings.setValue("manually_worked_parks", list(self.manually_worked_parks))
        self.recompute_comparisons()

        if is_now_worked:
            self.prompt_spot_on_pota(ref, activator_call)

    def toggle_selected_park_worked(self):
        cs = self.get_selected_compared_spot()
        if cs and cs.spot.reference:
            self.toggle_park_worked(cs.spot.reference, activator_call=cs.spot.activator)

    def on_table_selection_changed(self):
        cs = self.get_selected_compared_spot()
        if not cs:
            self.lbl_selection_info.setText("Select a park from the table for detailed info.")
            self.btn_open_park.setEnabled(False)
            self.btn_open_qrz.setEnabled(False)
            self.btn_spot_intel.setEnabled(False)
            if hasattr(self, "btn_mark_worked"):
                self.btn_mark_worked.setEnabled(False)
                self.btn_mark_worked.setText("Mark [WORKED]")
            return

        if hasattr(self, "btn_mark_worked"):
            self.btn_mark_worked.setEnabled(True)
            if cs.spot.reference in self.manually_worked_parks:
                self.btn_mark_worked.setText("Unmark [WORKED]")
            else:
                self.btn_mark_worked.setText("Mark [WORKED]")

        status_text = (
            "UNHUNTED PARK"
            if cs.is_new
            else f"HUNTED ({cs.qsos_hunted} QSOs, First: {cs.hunted_park.first_qso_date if cs.hunted_park else 'N/A'})"
        )
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
        self.btn_open_qrz.setEnabled(bool(cs.spot.activator))
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

        if cs.spot.reference in self.manually_worked_parks:
            act_worked = QAction(f"Unmark [WORKED] Status for Park {cs.spot.reference}", self)
        else:
            act_worked = QAction(f"Mark Park {cs.spot.reference} as [WORKED]", self)
        act_worked.triggered.connect(lambda: self.toggle_park_worked(cs.spot.reference))
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
        settings.setValue("manually_worked_parks", list(self.manually_worked_parks))
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("POTA Hunter")
    window = POTAHunterApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
