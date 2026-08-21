"""
POTA Hunter - Real-Time Lightning & Atmospheric QRN Noise Engine
Monitors live convective thunderstorm cells and lightning activity within 750 miles (1,200 km),
calculating dynamic ITU-R P.372 atmospheric noise (QRN) surges across amateur radio HF bands.

Architecture:
1. Instant Startup Bootstrap: Initializes immediately with active NOAA NWS convective alerts (0s delay).
2. Live WebSocket Stream: Resilient background thread connects to Blitzortung WebSocket servers
   (ws1, ws7, ws8.blitzortung.org) using pure Python socket/ssl/struct with standard LZW decompression.
3. Time-Decayed Running Counts & Rates: Tracks live strikes in a 60-minute sliding window with
   exponential time-decay weighting (0-10m: 100%, 10-20m: 70%, 20-30m: 45%, 30-60m: 20%).
4. NWS Warning Polygon Correlation: Cross-references live strikes with active NWS warning polygons
   to compute exact strike counts inside each warning area.
5. Exact UI / Tooltip Consistency: Preserves the standardized 1-to-10 severity scale and rich HTML layout.
"""

import json
import logging
import math
import random
import socket
import ssl
import struct
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Operational radius: 750 miles (1,207 km)
MAX_QRN_RADIUS_MILES = 750.0
EARTH_RADIUS_KM = 6371.0
EARTH_RADIUS_MILES = 3958.8

# Blitzortung WebSocket Servers
BLITZORTUNG_WS_HOSTS = [
    "ws7.blitzortung.org",
    "ws1.blitzortung.org",
    "ws8.blitzortung.org",
]


# =====================================================================
# Pure Python WebSocket & LZW Helpers (Zero External Dependencies)
# =====================================================================

def lzw_decode(data_str: str) -> str:
    """
    Decompresses LZW-encoded string as transmitted by Blitzortung WebSocket servers.
    Pure Python standard library implementation.
    """
    if not data_str:
        return ""
    dict_map: Dict[int, str] = {}
    curr_char = data_str[0]
    old_word = curr_char
    out = [curr_char]
    code = 256
    for i in range(1, len(data_str)):
        curr_code = ord(data_str[i])
        if curr_code < 256:
            phrase = data_str[i]
        else:
            phrase = dict_map.get(curr_code, old_word + curr_char)
        out.append(phrase)
        curr_char = phrase[0]
        dict_map[code] = old_word + curr_char
        code += 1
        old_word = phrase
    return "".join(out)


def make_ws_frame(msg: str) -> bytes:
    """Encodes a client-to-server masked WebSocket text frame."""
    payload = msg.encode("utf-8") if isinstance(msg, str) else msg
    length = len(payload)
    mask = bytes([random.randint(0, 255) for _ in range(4)])
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if length < 126:
        header = bytes([0x81, 0x80 | length]) + mask
    elif length < 65536:
        header = bytes([0x81, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF]) + mask
    else:
        header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", length) + mask
    return header + masked


def decode_ws_frame(data: bytes) -> Tuple[Optional[Tuple[int, bytes]], bytes]:
    """
    Decodes a server-to-client WebSocket frame.
    Returns ((opcode, payload_bytes), remaining_bytes) or (None, data) if incomplete.
    """
    if len(data) < 2:
        return None, data
    b1, b2 = data[0], data[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    payload_len = b2 & 0x7F
    idx = 2
    if payload_len == 126:
        if len(data) < idx + 2:
            return None, data
        payload_len = struct.unpack(">H", data[idx:idx + 2])[0]
        idx += 2
    elif payload_len == 127:
        if len(data) < idx + 8:
            return None, data
        payload_len = struct.unpack(">Q", data[idx:idx + 8])[0]
        idx += 8

    mask = None
    if masked:
        if len(data) < idx + 4:
            return None, data
        mask = data[idx:idx + 4]
        idx += 4

    if len(data) < idx + payload_len:
        return None, data

    payload = data[idx:idx + payload_len]
    rem = data[idx + payload_len:]
    if masked and mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return (opcode, payload), rem


# =====================================================================
# Geometry & Point-in-Polygon Helpers
# =====================================================================

def calculate_haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float]:
    """Calculates great-circle distance in miles and initial true bearing in degrees."""
    r_mi = EARTH_RADIUS_MILES
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(max(0.0, a)), math.sqrt(max(0.0, 1.0 - a)))
    distance_miles = r_mi * c

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing_deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return distance_miles, bearing_deg


def point_in_polygon(lon: float, lat: float, polygon: List[Tuple[float, float]]) -> bool:
    """
    Ray-casting point-in-polygon algorithm in pure Python.
    polygon is a list of (lon, lat) tuples.
    """
    if len(polygon) < 3:
        return False
    inside = False
    n = len(polygon)
    p1_lon, p1_lat = polygon[0]
    for i in range(1, n + 1):
        p2_lon, p2_lat = polygon[i % n]
        if min(p1_lat, p2_lat) < lat <= max(p1_lat, p2_lat):
            if lon <= max(p1_lon, p2_lon):
                if p1_lat != p2_lat:
                    x_inters = (lat - p1_lat) * (p2_lon - p1_lon) / (p2_lat - p1_lat) + p1_lon
                    if p1_lon == p2_lon or lon <= x_inters:
                        inside = not inside
        p1_lon, p1_lat = p2_lon, p2_lat
    return inside


# =====================================================================
# Data Structures
# =====================================================================

@dataclass
class LightningStrike:
    """Individual real-time lightning strike detected by Blitzortung network."""
    timestamp_utc: float
    latitude: float
    longitude: float
    distance_miles: float
    bearing_deg: float
    raw_delay: float = 0.0


@dataclass
class NWSWarning:
    """Active convective weather warning polygon from NOAA NWS."""
    event_type: str
    headline: str
    distance_miles: float
    bearing_deg: float
    polygon_coords: List[Tuple[float, float]] = field(default_factory=list)  # [(lon, lat), ...]
    issued_minutes_ago: int = 0
    expires_in_minutes: Optional[int] = None
    actual_strikes_in_polygon: int = 0


@dataclass
class StormCell:
    """Represents a localized convective thunderstorm cell or lightning cluster."""
    latitude: float
    longitude: float
    intensity_weight: float = 1.0  # 1.0 = moderate, 1.5 = tornado/supercell
    event_type: str = "Thunderstorm"
    headline: str = ""
    distance_miles: float = 0.0
    bearing_deg: float = 0.0
    estimated_strikes_per_min: int = 20
    estimated_strikes_15m: int = 300
    alert_age_minutes: int = 0
    expires_in_minutes: Optional[int] = None
    is_live_cluster: bool = False
    actual_strikes_in_polygon: int = 0
    total_strikes_in_cluster: int = 0
    cluster_window_minutes: int = 60
    movement_speed_mph: Optional[float] = None
    movement_heading_deg: Optional[float] = None
    is_approaching: bool = False
    estimated_toa_minutes: Optional[int] = None
    toa_label: str = "NA"


def heading_to_cardinal(deg: Optional[float]) -> str:
    """Converts a heading in degrees (0-360) into standard 8-point cardinal direction string."""
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int(round((deg % 360) / 45.0)) % 8
    return dirs[idx]


def compute_cluster_motion_and_toa(
    strikes: List[LightningStrike],
    home_lat: float,
    home_lon: float,
    current_dist_mi: float,
    current_bearing_deg: float,
) -> Tuple[Optional[float], Optional[float], bool, Optional[int], str]:
    """
    Analyzes the spatio-temporal distribution of strikes within a cluster to determine:
    1. Ground speed (mph)
    2. Movement heading (degrees true)
    3. Approach status towards operator's home QTH (within fuzzy tolerance ~35 miles)
    4. Estimated Time of Arrival (TOA in minutes)
    5. TOA display string (e.g. "25m", "45m", "1h 15m", or "NA")

    Returns:
        (speed_mph, heading_deg, is_approaching, estimated_toa_minutes, toa_label)
    """
    if len(strikes) < 5:
        return None, None, False, None, "NA"

    # Sort strikes chronologically
    sorted_strikes = sorted(strikes, key=lambda s: s.timestamp_utc)
    t_min = sorted_strikes[0].timestamp_utc
    t_max = sorted_strikes[-1].timestamp_utc
    delta_t_sec = t_max - t_min

    # Require at least 45 seconds baseline span between earliest and newest strikes
    if delta_t_sec < 45.0:
        return None, None, False, None, "NA"

    # Use the earliest 33% and latest 33% of strikes to establish a firmer temporal baseline.
    # This avoids centroid drift from noisy, symmetric flashing in the middle of the cluster.
    n_sample = max(2, len(sorted_strikes) // 3)
    early_strikes = sorted_strikes[:n_sample]
    late_strikes = sorted_strikes[-n_sample:]

    t1 = sum(s.timestamp_utc for s in early_strikes) / len(early_strikes)
    lat1 = sum(s.latitude for s in early_strikes) / len(early_strikes)
    lon1 = sum(s.longitude for s in early_strikes) / len(early_strikes)

    t2 = sum(s.timestamp_utc for s in late_strikes) / len(late_strikes)
    lat2 = sum(s.latitude for s in late_strikes) / len(late_strikes)
    lon2 = sum(s.longitude for s in late_strikes) / len(late_strikes)

    dt_hours = (t2 - t1) / 3600.0
    if dt_hours <= 0.01:  # less than 36 seconds difference between centroids
        return None, None, False, None, "NA"

    dist_moved_mi, heading_deg = calculate_haversine_miles(lat1, lon1, lat2, lon2)
    speed_mph = dist_moved_mi / dt_hours

    # Physical sanity filtering for convective cells: 1.5 mph to 90 mph
    if speed_mph < 1.5:
        return None, None, False, None, "NA"
        
    # Cap anomalous speed spikes instead of completely discarding the motion vector
    if speed_mph > 90.0:
        speed_mph = 90.0

    # Vector pointing from current cluster location towards operator's home QTH
    # Cluster is at bearing current_bearing_deg FROM home QTH, so vector toward home is (current_bearing_deg + 180) % 360
    vector_to_home_deg = (current_bearing_deg + 180.0) % 360.0

    # Divergence angle between storm movement direction and line towards home
    diff_angle_deg = abs(heading_deg - vector_to_home_deg) % 360.0
    if diff_angle_deg > 180.0:
        diff_angle_deg = 360.0 - diff_angle_deg

    # Check if moving towards home within ~70 degrees azimuth cone
    if diff_angle_deg <= 70.0:
        rad = math.radians(diff_angle_deg)
        closing_speed_mph = speed_mph * math.cos(rad)
        cpa_distance_mi = current_dist_mi * math.sin(rad)

        # Approaching if closing speed >= 5 mph and closest approach is within fuzzy grid range (<= 35 miles)
        if closing_speed_mph >= 5.0 and cpa_distance_mi <= 35.0:
            # Time of Arrival in minutes
            toa_minutes = max(1, int(round((current_dist_mi / closing_speed_mph) * 60.0)))
            if toa_minutes <= 240:  # within 4 hours
                if toa_minutes >= 60:
                    h = toa_minutes // 60
                    m = toa_minutes % 60
                    toa_str = f"{h}h {m}m" if m > 0 else f"{h}h"
                else:
                    toa_str = f"{toa_minutes}m"
                return round(speed_mph, 1), round(heading_deg, 1), True, toa_minutes, toa_str

    return round(speed_mph, 1), round(heading_deg, 1), False, None, "NA"


@dataclass
class LightningActivityLevel:
    """Standardized 1-to-10 scale representing regional lightning & atmospheric noise threat."""
    level: int          # 1 to 10
    color: str          # Hex color code for UI
    label: str          # Short label
    short_text: str     # Single digit for dashboard card
    advisory: str       # Operating safety recommendation
    description: str    # Detailed explanation
    is_disconnect_advisory: bool = False


@dataclass
class RegionalLightningSummary:
    """Summary of regional lightning & convective thunderstorm activity within 750 miles."""
    active_storm_count: int = 0
    total_strikes_detected: int = 0
    strike_rate_per_min: int = 0
    strike_rate_per_hour: int = 0
    closest_storm_miles: Optional[float] = None
    closest_storm_bearing: Optional[float] = None
    storm_cells: List[StormCell] = field(default_factory=list)
    nws_warnings: List[NWSWarning] = field(default_factory=list)
    qrn_surge_20m_db: float = 0.0
    qrn_surge_40m_db: float = 0.0
    qrn_surge_80m_db: float = 0.0
    qrn_surge_160m_db: float = 0.0
    status_text: str = "Clear / Low QRN"
    updated_at: str = "Not fetched"
    source: str = "NOAA NWS / Convective Radar"
    is_live_stream_active: bool = False
    live_strikes_tracked: int = 0

    def get_activity_level(self) -> LightningActivityLevel:
        """
        Computes standardized 1-to-10 lightning threat & QRN noise scale.
        Based on real strike proximity, density, and time-decayed strike counts.
        """
        if not self.storm_cells or self.closest_storm_miles is None:
            return LightningActivityLevel(
                level=1,
                color="#2ea043",
                label="Clear",
                short_text="1",
                advisory="Normal operating conditions. All bands clear.",
                description="No active convective storm cells detected within 750 miles.",
                is_disconnect_advisory=False,
            )

        d = self.closest_storm_miles
        d_round = int(round(d))
        d_str = f"~{d_round} mi" if d_round > 0 else "< 1 mi"

        # Base level from closest storm/strike distance
        if d <= 8.0:
            base_level = 10
        elif d <= 20.0:
            base_level = 9
        elif d <= 45.0:
            base_level = 8
        elif d <= 85.0:
            base_level = 7
        elif d <= 140.0:
            base_level = 6
        elif d <= 220.0:
            base_level = 5
        elif d <= 350.0:
            base_level = 4
        elif d <= 500.0:
            base_level = 3
        elif d <= 750.0:
            base_level = 2
        else:
            base_level = 1

        # Frequent lightning boost: multiple active cells within 60 mi or high cluster density within 100 mi
        nearby_60_count = sum(1 for c in self.storm_cells if c.distance_miles <= 60.0)
        nearby_100_count = sum(1 for c in self.storm_cells if c.distance_miles <= 100.0)
        is_frequent = (nearby_60_count >= 3) or (nearby_100_count >= 5)
        # Cap boost at level 8 so Level 9/10 disconnect warnings are strictly reserved for physically close storms (<= 20 mi)
        level = min(8, base_level + 1) if (is_frequent and base_level < 8) else base_level
        boosted = (level > base_level)

        if level == 10:
            color = "#ff2a55"
            label = "Immediate Hazard"
            short_text = "10"
            advisory = f"🚨 DANGER: Lightning in immediate vicinity ({d_str})! Disconnect all antennas and unplug rigs now."
            description = f"Lightning strikes in immediate vicinity ({d_str}). S9+20 to S9+40 static crashes."
            is_disc = True
        elif level == 9:
            color = "#f85149"
            short_text = "9"
            is_disc = True
            if boosted:
                label = "Frequent Lightning"
                advisory = f"⚠️ WARNING: Frequent regional lightning ({nearby_60_count} active clusters, closest {d_str})! Monitor conditions and consider disconnecting feedlines."
                description = f"Frequent lightning activity within 60 mi (closest {d_str}). Heavy static crashes and elevated QRN."
            else:
                label = "Very Close Proximity"
                advisory = f"⚠️ WARNING: Lightning within {d_str}! Consider disconnecting antenna feedlines and rotor cables."
                description = f"Thunderstorms active at {d_str} (8–20 mi range). S9+ static. Risk of electrostatic induction."
        elif level == 8:
            color = "#da3633"
            short_text = "8"
            is_disc = False
            if boosted:
                label = "Frequent Lightning"
                advisory = f"Heavy local QRN from frequent regional lightning (closest {d_str}). Storms approaching — watch conditions closely."
                description = f"Frequent lightning activity within 60–100 mi (closest {d_str}). Heavy S7–S9 static crashes across lower HF bands."
            else:
                label = "Close Storms"
                advisory = "Heavy local QRN. Storms approaching your area — watch conditions closely."
                description = f"Thunderstorms active at {d_str} (20–45 mi range). Heavy S7–S9 static crashes across lower HF bands."
        elif level == 7:
            color = "#e06c3a"
            short_text = "7"
            is_disc = False
            if boosted:
                label = "Frequent Lightning"
                advisory = f"Heavy QRN on lower bands from frequent lightning (closest {d_str}). Consider higher bands or shorter sessions."
                description = f"Frequent lightning clusters within 100 mi (closest {d_str}). S5–S7 static on low/mid bands."
            else:
                label = "Storms Nearby"
                advisory = "Heavy QRN on lower bands. Consider higher bands or shorter sessions."
                description = f"Active thunderstorm clusters at {d_str} (45–85 mi range). S5–S7 static on low/mid bands."
        elif level == 6:
            color = "#f0883e"
            short_text = "6"
            is_disc = False
            if boosted:
                label = "Frequent Lightning"
                advisory = f"Frequent static crashes from regional lightning (closest {d_str}). Monitor storm movement."
                description = f"Frequent lightning activity within 100 mi (closest {d_str}). Noticeable QRN on 40m/80m."
            else:
                label = "Notable"
                advisory = "Frequent static crashes. Monitor storm movement."
                description = f"Thunderstorms active at {d_str} (85–140 mi range). Noticeable QRN on 40m/80m; 20m may have some hash."
        elif level == 5:
            color = "#db6d28"
            label = "Elevated"
            short_text = "5"
            advisory = "Elevated noise floor on 40m/80m. Consider higher bands if available."
            description = f"Active thunderstorms at {d_str} (140–220 mi range). Noise floor elevated on 40m/80m."
            is_disc = False
        elif level == 4:
            color = "#d29922"
            label = "Moderate"
            short_text = "4"
            advisory = "Noticeable static crashes on 40m/80m. Weak DX signals may be affected."
            description = f"Regional storm clusters at {d_str} (220–350 mi range). Elevated hash on lower HF bands."
            is_disc = False
        elif level == 3:
            color = "#7ee787"
            label = "Low"
            short_text = "3"
            advisory = "Low background sferics. Minor static on 80m/160m."
            description = f"Distant storm clusters at {d_str} (350–500 mi range). Minor low-band noise — 20m and above unaffected."
            is_disc = False
        elif level == 2:
            color = "#3fb950"
            label = "Very Low"
            short_text = "2"
            advisory = "Distant storms. Bands clear."
            description = f"Distant storm cells at {d_str} (500–750 mi range). Negligible background sferics."
            is_disc = False
        else:
            color = "#2ea043"
            label = "Clear"
            short_text = "1"
            advisory = "Normal operating conditions. All bands clear."
            description = "No active convective storm cells detected within 750 miles."
            is_disc = False

        return LightningActivityLevel(
            level=level,
            color=color,
            label=label,
            short_text=short_text,
            advisory=advisory,
            description=description,
            is_disconnect_advisory=is_disc,
        )

    def format_tooltip_html(self) -> str:
        """Formats rich HTML tooltip for GUI mouseover with dedicated NWS warning and live lightning activity sections."""
        act = self.get_activity_level()
        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 12px; color: #e6edf3; line-height: 1.4;'>")
        lines.append(
            f"<div style='font-size: 14px; font-weight: bold; color: {act.color}; margin-bottom: 4px;'>"
            f"⚡ Regional Lightning Activity: Level {act.level}/10 ({act.label})</div>"
        )
        lines.append(f"<div style='color: #8b949e; margin-bottom: 8px;'>{act.description}</div>")

        # -------------------------------------------------------------
        # Section 1: Nearest NWS Warning
        # -------------------------------------------------------------
        lines.append("<div style='margin-bottom: 2px;'><b>Nearest NWS Warning:</b></div>")
        closest_nws: Optional[NWSWarning] = (
            min(self.nws_warnings, key=lambda w: w.distance_miles) if self.nws_warnings else None
        )
        # Fallback if nws_warnings list was not directly attached but storm_cells has NWS alert cells
        if not closest_nws and self.storm_cells:
            nws_cells = [c for c in self.storm_cells if not c.is_live_cluster and c.event_type != "Live Lightning Cluster"]
            if nws_cells:
                best_c = min(nws_cells, key=lambda c: c.distance_miles)
                closest_nws = NWSWarning(
                    event_type=best_c.event_type,
                    headline=best_c.headline,
                    distance_miles=best_c.distance_miles,
                    bearing_deg=best_c.bearing_deg,
                    issued_minutes_ago=best_c.alert_age_minutes,
                    expires_in_minutes=best_c.expires_in_minutes,
                    actual_strikes_in_polygon=best_c.actual_strikes_in_polygon,
                )

        if closest_nws:
            w_dist = closest_nws.distance_miles
            w_bearing = int(closest_nws.bearing_deg)
            w_exp = closest_nws.expires_in_minutes
            if w_exp is not None:
                if w_exp <= 0:
                    w_exp_str = " (expires soon)"
                elif w_exp >= 60:
                    h = w_exp // 60
                    m = w_exp % 60
                    w_exp_str = f" (expires in {h}h {m}m)" if m > 0 else f" (expires in {h}h)"
                else:
                    w_exp_str = f" (expires in {w_exp}m)"
            else:
                w_exp_str = ""
            w_strikes = closest_nws.actual_strikes_in_polygon
            w_age = closest_nws.issued_minutes_ago
            match_cell = next(
                (c for c in self.storm_cells if c.event_type == closest_nws.event_type and abs(c.distance_miles - closest_nws.distance_miles) < 10.0),
                None,
            )
            w_strikes_15m = match_cell.estimated_strikes_15m if match_cell else (w_strikes if w_strikes > 0 else 75)
            w_rate = match_cell.estimated_strikes_per_min if match_cell else (max(1, int(round(w_strikes / 15.0))) if w_strikes > 0 else (5 if w_age <= 30 else 1))

            lines.append(
                f"<div style='color: #f85149; font-weight: bold; margin-left: 6px; margin-bottom: 2px;'>"
                f"{closest_nws.event_type} — {w_dist:.1f} miles @ {w_bearing}°"
                f"<span style='color: #8b949e; font-size: 11px; font-weight: normal;'>{w_exp_str}</span></div>"
            )
            if self.is_live_stream_active and w_strikes > 0:
                lines.append(
                    f"<div style='color: #c9d1d9; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>"
                    f"↳ Live Activity in Polygon: <b>~{w_rate} strikes/min</b> · <b>{w_strikes} strikes</b> in warning polygon</div>"
                )
            elif self.is_live_stream_active and w_strikes == 0 and "Hybrid" in self.source:
                lines.append(
                    f"<div style='color: #c9d1d9; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>"
                    f"↳ Blended Warning Activity: <b>~{w_rate} strikes/min</b> · <b>~{w_strikes_15m} strikes</b> (NWS model blending with live stream)</div>"
                )
            else:
                lines.append(
                    f"<div style='color: #c9d1d9; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>"
                    f"↳ Modeled Activity in Polygon: <b>~{w_rate} strikes/min</b> · <b>~{w_strikes_15m} strikes</b> (NOAA NWS warning model)</div>"
                )
        else:
            lines.append("<div style='color: #8b949e; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>None active within 750 miles</div>")

        # -------------------------------------------------------------
        # Section 2: Nearest Lightning Activity
        # -------------------------------------------------------------
        lines.append("<div style='margin-bottom: 4px;'><b>Nearest Lightning Activity:</b></div>")
        active_cells = list(self.storm_cells)
        if active_cells:
            active_cells.sort(key=lambda c: c.distance_miles)
            lines.append(
                "<table style='font-size: 11px; color: #c9d1d9; border-collapse: collapse; width: 100%; margin-left: 6px; margin-bottom: 8px;'>"
                "<tr style='color: #8b949e; border-bottom: 1px solid #30363d;'>"
                "<th style='text-align: left; padding: 2px 8px 2px 0;'>Distance</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Bearing</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Rate</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Motion / TOA</th>"
                "<th style='text-align: left; padding: 2px 0;'>Total Strikes (window)</th>"
                "</tr>"
            )
            nearest_cells = active_cells[:4]
            remaining_cells = active_cells[4:]
            approaching_cells = [c for c in remaining_cells if c.is_approaching][:2]
            cells_to_display = nearest_cells + approaching_cells

            for cluster in cells_to_display:
                window_min = cluster.cluster_window_minutes if cluster.cluster_window_minutes > 0 else 15
                total_stk = cluster.total_strikes_in_cluster if cluster.total_strikes_in_cluster > 0 else cluster.estimated_strikes_15m
                rate_stk = cluster.estimated_strikes_per_min

                if cluster.movement_speed_mph is not None and cluster.movement_heading_deg is not None:
                    cardinal = heading_to_cardinal(cluster.movement_heading_deg)
                    spd = int(round(cluster.movement_speed_mph))
                    if cluster.is_approaching and cluster.toa_label != "NA":
                        toa_html = f"<span style='color: #ffa657; font-weight: bold;'>{spd} mph → {cardinal} (TOA {cluster.toa_label})</span>"
                    else:
                        toa_html = f"<span style='color: #8b949e;'>{spd} mph → {cardinal} (TOA: NA)</span>"
                elif cluster.is_approaching and cluster.toa_label != "NA":
                    toa_html = f"<span style='color: #ffa657; font-weight: bold;'>Approaching (TOA {cluster.toa_label})</span>"
                else:
                    toa_html = "<span style='color: #8b949e;'>NA</span>"

                lines.append(
                    f"<tr>"
                    f"<td style='padding: 3px 8px 3px 0; color: #58a6ff; font-weight: bold;'>{cluster.distance_miles:.1f} mi</td>"
                    f"<td style='padding: 3px 8px;'>{int(cluster.bearing_deg)}°</td>"
                    f"<td style='padding: 3px 8px; color: #7ee787;'>~{rate_stk} stk/min</td>"
                    f"<td style='padding: 3px 8px;'>{toa_html}</td>"
                    f"<td style='padding: 3px 0;'>{total_stk} strikes (past {window_min}m)</td>"
                    f"</tr>"
                )
            lines.append("</table>")
        else:
            if not self.is_live_stream_active and self.total_strikes_detected == 0:
                lines.append("<div style='color: #8b949e; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>Connecting to live strike stream...</div>")
            else:
                lines.append("<div style='color: #8b949e; font-size: 11px; margin-left: 6px; margin-bottom: 8px;'>No strike clusters detected within 750 miles</div>")

        # -------------------------------------------------------------
        # Section 3: Regional Strike Totals (750 mi radius)
        # -------------------------------------------------------------
        time_window = "past 15 min" if not self.is_live_stream_active else "past 30 min"
        if self.total_strikes_detected > 0:
            lines.append(
                f"<div style='margin-bottom: 6px;'><b>Regional Strike Totals (750 mi radius):</b><br />"
                f"<span style='color: #58a6ff; font-weight: bold;'>~{self.total_strikes_detected:,} strikes</span> in {time_window} "
                f"<span style='color: #8b949e;'>(~{self.strike_rate_per_min} strikes/min · {self.active_storm_count} active clusters)</span></div>"
            )
        else:
            lines.append("<div style='margin-bottom: 6px;'><b>Regional Strike Totals:</b> 0 strikes (Low atmospheric noise)</div>")

        # -------------------------------------------------------------
        # Section 4: Band Atmospheric Noise Surges (QRN)
        # -------------------------------------------------------------
        lines.append("<div style='margin-top: 6px; margin-bottom: 4px;'><b>Band Atmospheric Noise Surges (QRN):</b></div>")
        lines.append("<table style='font-size: 11px; color: #c9d1d9; border-collapse: collapse;'>")
        lines.append(f"<tr><td style='padding-right: 12px;'>160m (1.9 MHz):</td><td><b style='color:#f85149;'>+{self.qrn_surge_160m_db:.1f} dB</b></td></tr>")
        lines.append(f"<tr><td style='padding-right: 12px;'>80m (3.7 MHz):</td><td><b style='color:#f85149;'>+{self.qrn_surge_80m_db:.1f} dB</b></td></tr>")
        lines.append(f"<tr><td style='padding-right: 12px;'>40m (7.1 MHz):</td><td><b style='color:#e06c3a;'>+{self.qrn_surge_40m_db:.1f} dB</b></td></tr>")
        lines.append(f"<tr><td style='padding-right: 12px;'>20m (14.1 MHz):</td><td><b style='color:#d29922;'>+{self.qrn_surge_20m_db:.1f} dB</b></td></tr>")
        lines.append("</table>")

        adv_box_style = (
            f"border: 1px solid {act.color}; background-color: rgba(255, 50, 50, 0.15);"
            if act.is_disconnect_advisory
            else "border: 1px solid #30363d; background-color: #161b22;"
        )
        lines.append(
            f"<div style='margin-top: 10px; padding: 6px 8px; border-radius: 4px; {adv_box_style}'>"
            f"<b>Station Safety Advisory:</b><br />{act.advisory}</div>"
        )

        lines.append(
            "<div style='margin-top: 8px; font-size: 10px; color: #8b949e; border-top: 1px solid #30363d; padding-top: 4px;'>"
            "Scale: 1-3 (Clear/Low) | 4-6 (Moderate/Notable) | 7-8 (Nearby) | 9-10 (⚠️ Disconnect Antennas!)"
            f" &nbsp;|&nbsp; <b>Last updated: {self.updated_at}</b> &nbsp;|&nbsp; Refreshes every 1–5 min"
            "</div>"
        )
        lines.append("</div>")
        return "".join(lines)

    def get_qrn_surge_db(self, freq_mhz: float) -> float:
        """
        Calculates dynamic QRN atmospheric noise surge in dB for any HF frequency
        based on active storm proximity and ITU-R P.372 inverse-frequency power law.
        """
        if not self.storm_cells or freq_mhz <= 0:
            return 0.0

        f = max(1.8, freq_mhz)
        # Sferics susceptibility scales strongly with lower frequencies (~ 1/f^1.5)
        freq_factor = (14.0 / f) ** 1.5

        total_surge = 0.0
        for cell in self.storm_cells:
            d_mi = max(1.0, cell.distance_miles)
            if d_mi > MAX_QRN_RADIUS_MILES:
                continue
            dist_weight = 1.0 / (1.0 + (d_mi / 100.0) ** 1.8)
            # Increase base multiplier to represent extreme impulse power of lightning
            surge_contrib = cell.intensity_weight * 15.0 * dist_weight * freq_factor
            total_surge += surge_contrib

        # Use 10*log10 but with a powered total_surge to model the peak average power of static crashes
        effective_surge = 10.0 * math.log10(1.0 + total_surge ** 2.0)
        # Cap at 35 dB (approx 6 S-units of average noise floor degradation for nearby severe storms)
        return max(0.0, min(35.0, round(effective_surge, 1)))


# =====================================================================
# Real-Time Strike Sliding Window Buffer
# =====================================================================

class StrikeBuffer:
    """
    Thread-safe sliding-window buffer storing live lightning strikes
    detected within the 750-mile radius over a 60-minute window.
    """

    def __init__(self, max_age_seconds: float = 3600.0):
        self.max_age_seconds = max_age_seconds
        self._strikes: Deque[LightningStrike] = deque()
        self._lock = threading.Lock()

    def add_strike(self, strike: LightningStrike):
        with self._lock:
            self._strikes.append(strike)
            self._prune_unlocked(time.time())

    def _prune_unlocked(self, now: float):
        cutoff = now - self.max_age_seconds
        while self._strikes and self._strikes[0].timestamp_utc < cutoff:
            self._strikes.popleft()

    def clear(self):
        """Clears all buffered strikes (used on callsign/location change)."""
        with self._lock:
            self._strikes.clear()

    def get_all_strikes(self) -> List[LightningStrike]:
        with self._lock:
            now = time.time()
            self._prune_unlocked(now)
            return list(self._strikes)

    def get_strike_counts_and_rate(self) -> Tuple[int, int, int, float]:
        """
        Returns (count_15m, count_30m, count_60m, time_weighted_score).
        Time weights:
          0-10 min: 1.0
          10-20 min: 0.70
          20-30 min: 0.45
          30-60 min: 0.20
        """
        with self._lock:
            now = time.time()
            self._prune_unlocked(now)
            count_15m = 0
            count_30m = 0
            count_60m = len(self._strikes)
            weighted_score = 0.0

            for s in self._strikes:
                age_min = (now - s.timestamp_utc) / 60.0
                if age_min <= 15.0:
                    count_15m += 1
                if age_min <= 30.0:
                    count_30m += 1

                if age_min <= 10.0:
                    w = 1.0
                elif age_min <= 20.0:
                    w = 0.70
                elif age_min <= 30.0:
                    w = 0.45
                else:
                    w = 0.20
                weighted_score += w

            return count_15m, count_30m, count_60m, weighted_score

    def cluster_strikes(
        self, home_lat: float, home_lon: float, cluster_radius_miles: float = 35.0
    ) -> List[StormCell]:
        """
        Groups buffered strikes into localized spatial clusters (StormCell objects).
        """
        with self._lock:
            now = time.time()
            self._prune_unlocked(now)
            strikes = list(self._strikes)

        if not strikes:
            return []

        # Simple greedy spatial clustering
        clusters: List[List[LightningStrike]] = []
        for s in strikes:
            placed = False
            for c in clusters:
                rep = c[0]
                dist, _ = calculate_haversine_miles(s.latitude, s.longitude, rep.latitude, rep.longitude)
                if dist <= cluster_radius_miles:
                    c.append(s)
                    placed = True
                    break
            if not placed:
                clusters.append([s])

        storm_cells: List[StormCell] = []
        now = time.time()
        for c in clusters:
            avg_lat = sum(s.latitude for s in c) / len(c)
            avg_lon = sum(s.longitude for s in c) / len(c)
            dist_mi, bearing = calculate_haversine_miles(home_lat, home_lon, avg_lat, avg_lon)

            # Time-weighted cluster intensity and active duration
            recent_15m = sum(1 for s in c if (now - s.timestamp_utc) <= 900.0)
            rate_per_min = max(1, int(round(recent_15m / 15.0))) if recent_15m > 0 else (1 if len(c) > 1 else 0)
            
            # Base the intensity weight directly on the strike rate (strikes per minute)
            # A severe storm (60+ strikes/min) gets the massive weight multiplier of 4.0
            # An average pop-up storm (5-10 strikes/min) gets a standard weight (0.6 to 0.9)
            weight = max(0.3, min(4.0, 0.3 + (rate_per_min / 60.0) * 3.7)) if len(c) > 1 else 0.3

            oldest_ts = min(s.timestamp_utc for s in c)
            active_window_min = max(1, min(60, int(math.ceil((now - oldest_ts) / 60.0))))

            speed_mph, heading_deg, is_appr, toa_min, toa_lbl = compute_cluster_motion_and_toa(
                c, home_lat, home_lon, dist_mi, bearing
            )

            storm_cells.append(
                StormCell(
                    latitude=avg_lat,
                    longitude=avg_lon,
                    intensity_weight=round(weight, 2),
                    event_type="Live Lightning Cluster",
                    headline=f"{len(c)} strikes detected",
                    distance_miles=round(dist_mi, 1),
                    bearing_deg=round(bearing, 1),
                    estimated_strikes_per_min=rate_per_min,
                    estimated_strikes_15m=recent_15m,
                    alert_age_minutes=0,
                    is_live_cluster=True,
                    total_strikes_in_cluster=len(c),
                    cluster_window_minutes=active_window_min,
                    movement_speed_mph=speed_mph,
                    movement_heading_deg=heading_deg,
                    is_approaching=is_appr,
                    estimated_toa_minutes=toa_min,
                    toa_label=toa_lbl,
                )
            )

        storm_cells.sort(key=lambda x: x.distance_miles)
        return storm_cells


# =====================================================================
# Background Real-Time Blitzortung WebSocket Streaming Thread
# =====================================================================

class BlitzortungStreamThread(threading.Thread):
    """
    Dedicated background worker thread connecting via SSL WebSocket
    to Blitzortung real-time lightning feeds.
    Zero external dependencies — pure Python standard library.
    """

    def __init__(self, buffer: StrikeBuffer, home_lat: float, home_lon: float):
        super().__init__(daemon=True, name="BlitzortungStreamThread")
        self.buffer = buffer
        self.home_lat = home_lat
        self.home_lon = home_lon
        self._running = True
        self.is_connected = False
        self.connected_server = ""
        self.total_raw_strikes_received = 0
        self.regional_strikes_received = 0
        self.last_strike_time: Optional[float] = None
        self._coord_lock = threading.Lock()

    def update_home_location(self, lat: float, lon: float, reset_buffer: bool = True):
        with self._coord_lock:
            self.home_lat = lat
            self.home_lon = lon
        if reset_buffer:
            self.buffer.clear()
            self.regional_strikes_received = 0
            self.last_strike_time = None

    def stop(self):
        self._running = False

    def run(self):
        server_idx = 0
        while self._running:
            host = BLITZORTUNG_WS_HOSTS[server_idx % len(BLITZORTUNG_WS_HOSTS)]
            server_idx += 1
            try:
                self._connect_and_stream(host)
            except Exception as e:
                logger.debug("Blitzortung WS (%s) connection disconnected: %s", host, e)
                self.is_connected = False

            if self._running:
                # Reconnect backoff
                time.sleep(3.0)

    def _connect_and_stream(self, host: str):
        context = ssl.create_default_context()
        raw_sock = socket.create_connection((host, 443), timeout=8)
        ssock = context.wrap_socket(raw_sock, server_hostname=host)
        ssock.settimeout(45.0)

        key = "dGhlIHNhbXBsZSBub25jZQ=="
        req = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: https://map.blitzortung.org\r\n"
            f"User-Agent: POTA-Hunter/26.8.17-10\r\n\r\n"
        )
        ssock.sendall(req.encode("utf-8"))
        handshake_resp = ssock.recv(2048)
        if b"101 Switching Protocols" not in handshake_resp:
            ssock.close()
            return

        # Send subscription message: {"a": 111}
        ssock.sendall(make_ws_frame(json.dumps({"a": 111})))
        self.is_connected = True
        self.connected_server = host
        logger.info("Connected to real-time Blitzortung WebSocket (%s)", host)

        buf = b""
        last_ping_time = time.time()

        while self._running:
            try:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                buf += chunk

                while buf:
                    frame, buf = decode_ws_frame(buf)
                    if frame is None:
                        break
                    opcode, payload = frame
                    if opcode == 1:  # Text frame
                        raw_text = payload.decode("utf-8", errors="ignore")
                        decompressed = lzw_decode(raw_text)
                        try:
                            obj = json.loads(decompressed)
                            self._handle_incoming_strike(obj)
                        except Exception:
                            pass
                    elif opcode == 9:  # Ping frame
                        # Send pong
                        pong = bytes([0x8A, 0x80]) + b"\x12\x34\x56\x78"
                        ssock.sendall(pong)
                    elif opcode == 8:  # Close frame
                        ssock.close()
                        return

                # Send heartbeat ping every 25s if quiet
                if time.time() - last_ping_time > 25.0:
                    ping = bytes([0x89, 0x80]) + b"\x12\x34\x56\x78"
                    ssock.sendall(ping)
                    last_ping_time = time.time()

            except socket.timeout:
                # Timeout is normal — send WebSocket ping
                try:
                    ping = bytes([0x89, 0x80]) + b"\x12\x34\x56\x78"
                    ssock.sendall(ping)
                    last_ping_time = time.time()
                except Exception:
                    break
            except Exception as e:
                logger.debug("Socket read error: %s", e)
                break

        try:
            ssock.close()
        except Exception:
            pass
        self.is_connected = False

    def _handle_incoming_strike(self, strike_dict: dict):
        lat = strike_dict.get("lat")
        lon = strike_dict.get("lon")
        if lat is None or lon is None:
            return

        self.total_raw_strikes_received += 1
        with self._coord_lock:
            h_lat, h_lon = self.home_lat, self.home_lon

        dist_mi, bearing = calculate_haversine_miles(h_lat, h_lon, float(lat), float(lon))
        if dist_mi <= MAX_QRN_RADIUS_MILES:
            t_raw = strike_dict.get("time")
            # Convert nanosecond timestamp or default to current time
            if t_raw and isinstance(t_raw, (int, float)) and t_raw > 1e15:
                t_sec = float(t_raw) / 1e9
            else:
                t_sec = time.time()

            delay = float(strike_dict.get("delay", 0.0) or 0.0)
            strike = LightningStrike(
                timestamp_utc=t_sec,
                latitude=float(lat),
                longitude=float(lon),
                distance_miles=round(dist_mi, 1),
                bearing_deg=round(bearing, 1),
                raw_delay=delay,
            )
            self.buffer.add_strike(strike)
            self.regional_strikes_received += 1
            self.last_strike_time = time.time()


# =====================================================================
# Main Singleton Lightning Engine
# =====================================================================

class LightningEngine:
    """
    Singleton service managing hybrid real-time lightning monitoring:
    1. Instant NOAA NWS convective alert bootstrap for 0-delay startup.
    2. Background Blitzortung WebSocket live strike stream.
    3. Dynamic time-decay weighted strike rates and ITU-R P.372 QRN calculations.
    4. Real-time strike counting inside active NWS warning polygons.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LightningEngine, cls).__new__(cls)
                cls._instance._init_engine()
            return cls._instance

    def _init_engine(self):
        self.strike_buffer = StrikeBuffer(max_age_seconds=3600.0)
        self.stream_thread: Optional[BlitzortungStreamThread] = None
        self.cached_summary: Optional[RegionalLightningSummary] = None
        self.cached_nws_warnings: List[NWSWarning] = []
        self.last_nws_fetch_time: Optional[datetime] = None
        self.last_summary_time: Optional[datetime] = None
        self.current_home_lat: Optional[float] = None
        self.current_home_lon: Optional[float] = None
        self.start_time = time.time()
        self.cache_ttl_seconds = 60.0  # 1-minute summary cache
        self.nws_ttl_seconds = 180.0    # 3-minute NWS polygon cache

    def reset_home_location(self, home_lat: float, home_lon: float):
        """
        Resets lightning monitoring to new coordinates (e.g. on callsign or grid change):
        1. Clears strike buffer and raw counts.
        2. Invalidates cached summary and cached NWS warnings.
        3. Resets start timestamp to trigger instant NWS convective bootstrap for the new location.
        4. Updates background WebSocket stream coordinates to new location.
        """
        with self._lock:
            self.current_home_lat = home_lat
            self.current_home_lon = home_lon
            self.strike_buffer.clear()
            self.cached_summary = None
            self.cached_nws_warnings = []
            self.last_nws_fetch_time = None
            self.last_summary_time = None
            self.start_time = time.time()
            if self.stream_thread is not None and hasattr(self.stream_thread, "is_alive") and self.stream_thread.is_alive():
                if hasattr(self.stream_thread, "update_home_location"):
                    self.stream_thread.update_home_location(home_lat, home_lon, reset_buffer=True)
            else:
                self.start_stream_if_needed(home_lat, home_lon)

    def start_stream_if_needed(self, home_lat: float, home_lon: float):
        """Starts or updates the background WebSocket stream thread for operator coordinates."""
        if self.stream_thread is None or not (hasattr(self.stream_thread, "is_alive") and self.stream_thread.is_alive()):
            self.stream_thread = BlitzortungStreamThread(self.strike_buffer, home_lat, home_lon)
            self.stream_thread.start()
        elif hasattr(self.stream_thread, "update_home_location"):
            self.stream_thread.update_home_location(home_lat, home_lon, reset_buffer=False)

    def get_regional_lightning(
        self,
        home_lat: float,
        home_lon: float,
        force_refresh: bool = False,
        timeout: int = 5,
    ) -> RegionalLightningSummary:
        """
        Retrieves regional lightning activity and QRN surge relative to home coordinates.
        Uses instant NWS bootstrap for immediate startup, transitioning to live strike streaming.
        """
        # Check if operator location has changed by more than 5 miles
        if self.current_home_lat is None or self.current_home_lon is None:
            self.current_home_lat = home_lat
            self.current_home_lon = home_lon
        else:
            d_shift, _ = calculate_haversine_miles(self.current_home_lat, self.current_home_lon, home_lat, home_lon)
            if d_shift > 5.0:
                self.reset_home_location(home_lat, home_lon)

        self.start_stream_if_needed(home_lat, home_lon)

        now = datetime.now(timezone.utc)
        if (
            not force_refresh
            and self.cached_summary is not None
            and self.last_summary_time is not None
        ):
            age = (now - self.last_summary_time).total_seconds()
            stream_uptime = time.time() - self.start_time
            effective_ttl = 4.0 if stream_uptime < 30.0 else (8.0 if stream_uptime < 60.0 else self.cache_ttl_seconds)
            if age < effective_ttl:
                return self.cached_summary

        summary = self._compute_hybrid_summary(home_lat, home_lon, timeout=timeout)
        self.cached_summary = summary
        self.last_summary_time = now
        return summary

    def _fetch_nws_warnings_if_needed(self, home_lat: float, home_lon: float, timeout: int = 5) -> List[NWSWarning]:
        """Fetches active severe thunderstorm and tornado warnings from NOAA NWS."""
        now = datetime.now(timezone.utc)
        if self.cached_nws_warnings and self.last_nws_fetch_time is not None:
            if (now - self.last_nws_fetch_time).total_seconds() < self.nws_ttl_seconds:
                return self.cached_nws_warnings

        warnings: List[NWSWarning] = []
        url = (
            "https://api.weather.gov/alerts/active"
            "?status=actual&event=Severe%20Thunderstorm%20Warning,Tornado%20Warning,"
            "Flash%20Flood%20Warning,Special%20Marine%20Warning"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "POTA-Hunter-Propagation-Engine/26.8.17-10",
                    "Accept": "application/geo+json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    features = data.get("features", [])
                    now_utc = datetime.now(timezone.utc)
                    for feat in features:
                        geom = feat.get("geometry")
                        props = feat.get("properties", {})
                        if not geom:
                            continue
                        event_name = props.get("event", "Thunderstorm Warning")
                        headline = props.get("headline") or event_name

                        # Alert age
                        alert_age_minutes = 0
                        for time_key in ("onset", "sent", "effective"):
                            time_str = props.get(time_key)
                            if time_str:
                                try:
                                    dt = datetime.fromisoformat(time_str)
                                    if dt.tzinfo is None:
                                        dt = dt.replace(tzinfo=timezone.utc)
                                    age_secs = (now_utc - dt).total_seconds()
                                    alert_age_minutes = max(0, int(age_secs / 60))
                                    break
                                except Exception:
                                    pass

                        # Alert expiration
                        expires_in_minutes = None
                        for exp_key in ("expires", "ends"):
                            exp_str = props.get(exp_key)
                            if exp_str:
                                try:
                                    dt_exp = datetime.fromisoformat(exp_str)
                                    if dt_exp.tzinfo is None:
                                        dt_exp = dt_exp.replace(tzinfo=timezone.utc)
                                    exp_secs = (dt_exp - now_utc).total_seconds()
                                    expires_in_minutes = max(0, int(round(exp_secs / 60)))
                                    break
                                except Exception:
                                    pass

                        # Extract polygon vertices
                        coords_list: List[Tuple[float, float]] = []
                        geom_type = geom.get("type")
                        if geom_type == "Polygon":
                            raw_coords = geom.get("coordinates", [[]])[0]
                            coords_list = [(float(c[0]), float(c[1])) for c in raw_coords if len(c) >= 2]
                        elif geom_type == "MultiPolygon":
                            for poly in geom.get("coordinates", []):
                                if poly and len(poly) > 0:
                                    coords_list.extend([(float(c[0]), float(c[1])) for c in poly[0] if len(c) >= 2])

                        if not coords_list:
                            continue

                        avg_lon = sum(c[0] for c in coords_list) / len(coords_list)
                        avg_lat = sum(c[1] for c in coords_list) / len(coords_list)
                        dist_mi, bearing = calculate_haversine_miles(home_lat, home_lon, avg_lat, avg_lon)

                        if dist_mi <= MAX_QRN_RADIUS_MILES:
                            warnings.append(
                                NWSWarning(
                                    event_type=event_name,
                                    headline=headline,
                                    distance_miles=round(dist_mi, 1),
                                    bearing_deg=round(bearing, 1),
                                    polygon_coords=coords_list,
                                    issued_minutes_ago=alert_age_minutes,
                                    expires_in_minutes=expires_in_minutes,
                                )
                            )
        except Exception as e:
            logger.debug("Failed to fetch NWS alerts: %s", e)

        self.cached_nws_warnings = warnings
        self.last_nws_fetch_time = now
        return warnings

    def _compute_hybrid_summary(self, home_lat: float, home_lon: float, timeout: int = 5) -> RegionalLightningSummary:
        """
        Generates comprehensive summary smoothly blending NOAA NWS convective alert estimates
        into real-time Blitzortung WebSocket live strike telemetry over a 15-minute warmup window.
        """
        nws_warnings = self._fetch_nws_warnings_if_needed(home_lat, home_lon, timeout=timeout)
        count_15m, count_30m, count_60m, _ = self.strike_buffer.get_strike_counts_and_rate()
        all_live_strikes = self.strike_buffer.get_all_strikes()

        # Calculate exact real strikes within each NWS polygon
        if all_live_strikes and nws_warnings:
            for w in nws_warnings:
                if w.polygon_coords:
                    poly_strikes = sum(
                        1 for s in all_live_strikes
                        if point_in_polygon(s.longitude, s.latitude, w.polygon_coords)
                    )
                    w.actual_strikes_in_polygon = poly_strikes

        live_clusters = self.strike_buffer.cluster_strikes(home_lat, home_lon)
        stream_uptime = time.time() - self.start_time
        is_stream_live = (self.stream_thread is not None and self.stream_thread.is_connected)

        # -------------------------------------------------------------
        # Smooth Blending Weight: 15-minute (900s) continuous alpha ramp
        # -------------------------------------------------------------
        WARMUP_SECONDS = 900.0  # 15 min sliding window saturation
        if not is_stream_live:
            blitz_weight = 0.0
        else:
            alpha_time = min(1.0, stream_uptime / WARMUP_SECONDS)
            alpha_count = min(1.0, len(all_live_strikes) / 50.0)
            blitz_weight = min(1.0, max(alpha_time, alpha_count * 0.5))

        nws_weight = 1.0 - blitz_weight

        # -------------------------------------------------------------
        # Build Synthesized / Blended Storm Cells
        # -------------------------------------------------------------
        storm_cells: List[StormCell] = []

        # 1. Process active NWS Convective Warnings
        for w in nws_warnings:
            # Time discount factor for older warnings
            if w.issued_minutes_ago > 90:
                age_factor = 0.25
            elif w.issued_minutes_ago > 60:
                age_factor = 0.45
            elif w.issued_minutes_ago > 30:
                age_factor = 0.70
            else:
                age_factor = 1.0

            if "Tornado" in w.event_type:
                base_intensity = 1.5
                base_rate = 25.0
            elif "Severe Thunderstorm" in w.event_type:
                base_intensity = 1.0
                base_rate = 15.0
            elif "Marine" in w.event_type:
                base_intensity = 0.8
                base_rate = 10.0
            else:  # Flash Flood / other convective warnings
                base_intensity = 0.5
                base_rate = 5.0
            nws_weight_val = round(base_intensity * age_factor, 2)
            nws_model_rate = max(1, int(round(base_rate * nws_weight_val)))
            nws_model_15m = nws_model_rate * 15

            # Find real strikes inside this polygon
            poly_live_strikes = [
                s for s in all_live_strikes
                if w.polygon_coords and point_in_polygon(s.longitude, s.latitude, w.polygon_coords)
            ]

            # Determine coordinates: blend polygon centroid toward real strike center-of-mass
            if w.polygon_coords:
                poly_lon = sum(c[0] for c in w.polygon_coords) / len(w.polygon_coords)
                poly_lat = sum(c[1] for c in w.polygon_coords) / len(w.polygon_coords)
            else:
                poly_lat, poly_lon = home_lat, home_lon

            if poly_live_strikes and blitz_weight > 0.0:
                live_lon = sum(s.longitude for s in poly_live_strikes) / len(poly_live_strikes)
                live_lat = sum(s.latitude for s in poly_live_strikes) / len(poly_live_strikes)
                eff_lat = (1.0 - blitz_weight) * poly_lat + blitz_weight * live_lat
                eff_lon = (1.0 - blitz_weight) * poly_lon + blitz_weight * live_lon
                live_rate = max(1, int(round(len(poly_live_strikes) / max(1.0, min(15.0, stream_uptime / 60.0)))))
                live_15m = int(round(live_rate * 15)) if stream_uptime < 900.0 else len(poly_live_strikes)
            else:
                eff_lat, eff_lon = poly_lat, poly_lon
                live_rate = 0
                live_15m = 0

            dist_mi, bearing = calculate_haversine_miles(home_lat, home_lon, eff_lat, eff_lon)

            speed_mph, heading_deg, is_appr, toa_min, toa_lbl = compute_cluster_motion_and_toa(
                poly_live_strikes, home_lat, home_lon, dist_mi, bearing
            )

            # Smoothly blend rate and 15m strike count
            if blitz_weight <= 0.0:
                blended_cell_rate = nws_model_rate
                blended_cell_15m = nws_model_15m
                cell_intensity = nws_weight_val
            elif blitz_weight >= 1.0 and poly_live_strikes:
                blended_cell_rate = live_rate
                blended_cell_15m = len(poly_live_strikes)
                cell_intensity = max(0.5, min(3.0, len(poly_live_strikes) / 10.0))
            else:
                blended_cell_rate = max(1 if (nws_weight > 0.1 or poly_live_strikes) else 0, int(round(nws_weight * nws_model_rate + blitz_weight * max(1, live_rate))))
                blended_cell_15m = max(1 if (nws_weight > 0.1 or poly_live_strikes) else 0, int(round(nws_weight * nws_model_15m + blitz_weight * live_15m)))
                cell_intensity = round(nws_weight * nws_weight_val + blitz_weight * max(0.5, min(2.0, max(1, len(poly_live_strikes)) / 10.0)), 2)

            storm_cells.append(
                StormCell(
                    latitude=eff_lat,
                    longitude=eff_lon,
                    intensity_weight=cell_intensity,
                    event_type=w.event_type,
                    headline=w.headline,
                    distance_miles=round(dist_mi, 1),
                    bearing_deg=round(bearing, 1),
                    estimated_strikes_per_min=blended_cell_rate,
                    estimated_strikes_15m=blended_cell_15m,
                    alert_age_minutes=w.issued_minutes_ago,
                    expires_in_minutes=w.expires_in_minutes,
                    actual_strikes_in_polygon=len(poly_live_strikes),
                    total_strikes_in_cluster=blended_cell_15m if blitz_weight < 0.5 else max(blended_cell_15m, len(poly_live_strikes)),
                    cluster_window_minutes=15,
                    movement_speed_mph=speed_mph,
                    movement_heading_deg=heading_deg,
                    is_approaching=is_appr,
                    estimated_toa_minutes=toa_min,
                    toa_label=toa_lbl,
                )
            )

        # 2. Add non-overlapping live Blitzortung clusters
        for cluster in live_clusters:
            is_in_nws = any(
                abs(c.distance_miles - cluster.distance_miles) < 20.0 and abs(c.bearing_deg - cluster.bearing_deg) < 30.0
                for c in storm_cells
            )
            if not is_in_nws:
                storm_cells.append(cluster)

        storm_cells.sort(key=lambda s: s.distance_miles)

        # -------------------------------------------------------------
        # Regional Aggregate Rates & Strike Totals
        # -------------------------------------------------------------
        if not storm_cells and len(all_live_strikes) == 0:
            total_rate = 0
            total_15m = 0
            source_desc = "NOAA NWS / Blitzortung Clear"
        else:
            nws_aggregate_rate = sum(
                max(1, int(round(20.0 * (1.5 if "Tornado" in w.event_type else 1.0))))
                for w in nws_warnings
            )
            nws_aggregate_15m = nws_aggregate_rate * 15

            live_effective_rate = max(1, int(round(count_15m / max(1.0, min(15.0, stream_uptime / 60.0))))) if count_15m > 0 else (len(live_clusters) * 2 if live_clusters else 0)
            live_effective_15m = count_30m if stream_uptime >= 900.0 else int(round(live_effective_rate * 15))

            if blitz_weight <= 0.0:
                total_rate = nws_aggregate_rate if nws_aggregate_rate > 0 else sum(c.estimated_strikes_per_min for c in storm_cells)
                total_15m = nws_aggregate_15m if nws_aggregate_15m > 0 else sum(c.estimated_strikes_15m for c in storm_cells)
                source_desc = "NOAA NWS Convective Alerts (Bootstrap)"
            elif blitz_weight >= 1.0:
                total_rate = live_effective_rate
                total_15m = count_30m if count_30m > 0 else sum(c.estimated_strikes_15m for c in storm_cells)
                source_desc = "Blitzortung Real-Time Live WebSocket"
            else:
                total_rate = max(1, int(round(nws_weight * nws_aggregate_rate + blitz_weight * live_effective_rate)))
                total_15m = max(1, int(round(nws_weight * nws_aggregate_15m + blitz_weight * live_effective_15m)))
                source_desc = f"Hybrid NWS + Blitzortung ({int(blitz_weight * 100)}% Live Stream)"

        now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        summary = RegionalLightningSummary(
            active_storm_count=len(storm_cells),
            total_strikes_detected=total_15m,
            strike_rate_per_min=total_rate,
            strike_rate_per_hour=count_60m,
            storm_cells=storm_cells,
            nws_warnings=nws_warnings,
            updated_at=now_str,
            source=source_desc,
            is_live_stream_active=is_stream_live,
            live_strikes_tracked=len(all_live_strikes),
        )

        if storm_cells:
            closest = storm_cells[0]
            summary.closest_storm_miles = closest.distance_miles
            summary.closest_storm_bearing = closest.bearing_deg

            summary.qrn_surge_20m_db = summary.get_qrn_surge_db(14.1)
            summary.qrn_surge_40m_db = summary.get_qrn_surge_db(7.1)
            summary.qrn_surge_80m_db = summary.get_qrn_surge_db(3.7)
            summary.qrn_surge_160m_db = summary.get_qrn_surge_db(1.9)

            bearing_int = int(closest.bearing_deg)
            dist_int = int(closest.distance_miles)
            if closest.distance_miles <= 150.0:
                summary.status_text = f"⚡ QRN: Storms {dist_int} mi @ {bearing_int}° (+{summary.qrn_surge_40m_db:.0f}dB on 40m)"
            elif closest.distance_miles <= 350.0:
                summary.status_text = f"⚡ Regional QRN: Storms {dist_int} mi @ {bearing_int}° (+{summary.qrn_surge_40m_db:.0f}dB on 40m)"
            else:
                summary.status_text = f"⚡ Distant QRN: {len(storm_cells)} storms within 750 mi (+{summary.qrn_surge_80m_db:.0f}dB on 80m)"
        else:
            summary.status_text = "Clear / Low Atmospheric QRN"

        return summary


_GLOBAL_LIGHTNING_ENGINE = LightningEngine()


def fetch_regional_lightning_summary(
    home_lat: float,
    home_lon: float,
    force_refresh: bool = False,
    timeout: int = 5,
) -> RegionalLightningSummary:
    """Convenience helper to retrieve live regional lightning summary."""
    return _GLOBAL_LIGHTNING_ENGINE.get_regional_lightning(
        home_lat=home_lat, home_lon=home_lon, force_refresh=force_refresh, timeout=timeout
    )


def reset_lightning_engine_location(
    home_lat: float,
    home_lon: float,
    timeout: int = 5,
) -> RegionalLightningSummary:
    """Resets lightning monitoring to new coordinates and returns instant NWS bootstrap summary."""
    _GLOBAL_LIGHTNING_ENGINE.reset_home_location(home_lat, home_lon)
    return _GLOBAL_LIGHTNING_ENGINE.get_regional_lightning(
        home_lat=home_lat, home_lon=home_lon, force_refresh=True, timeout=timeout
    )

