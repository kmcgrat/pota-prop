"""
POTA Data Engine
Handles reading hunter CSV files, querying the POTA live spot API,
frequency-to-band conversion, and comparing hunted parks against active spots.
"""

import csv
import json
import logging
import math
import os
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from propagation_engine import (
    DEFAULT_ANTENNA_TYPE,
    DEFAULT_HOME_GRID,
    DEFAULT_TX_POWER_WATTS,
    CallsignResolver,
    PropagationResult,
    SolarWeather,
    SpotEvidence,
    calculate_qso_probability,
    latlon_to_maidenhead,
    maidenhead_to_latlon,
    parse_spot_evidence,
)
from lightning_engine import fetch_regional_lightning_summary, RegionalLightningSummary
import concurrent.futures
import urllib.error

logger = logging.getLogger(__name__)

POTA_SPOT_API_URL = "https://api.pota.app/spot/activator"
POTA_STREAM_API_URL = "https://api.pota.app/spot"
DEFAULT_HUNTER_CSV_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "hunter_parks.csv")

# Ham Radio Band definitions (in kHz)
BAND_RANGES: List[Tuple[float, float, str]] = [
    (1800.0, 2000.0, "160m"),
    (3500.0, 4000.0, "80m"),
    (5250.0, 5450.0, "60m"),
    (7000.0, 7300.0, "40m"),
    (10100.0, 10150.0, "30m"),
    (14000.0, 14350.0, "20m"),
    (18068.0, 18168.0, "17m"),
    (21000.0, 21450.0, "15m"),
    (24890.0, 24990.0, "12m"),
    (28000.0, 29700.0, "10m"),
    (50000.0, 54000.0, "6m"),
    (70000.0, 70500.0, "4m"),
    (144000.0, 148000.0, "2m"),
    (222000.0, 225000.0, "1.25m"),
    (420000.0, 450000.0, "70cm"),
    (902000.0, 928000.0, "33cm"),
    (1240000.0, 1300000.0, "23cm"),
]

POTA_PREFIX_TO_COUNTRY: Dict[str, str] = {
    "US": "United States",
    "K": "United States",
    "KL": "Alaska",
    "KL7": "Alaska",
    "KH6": "Hawaii",
    "KP4": "Puerto Rico",
    "KP2": "US Virgin Islands",
    "KH2": "Guam",
    "VE": "Canada",
    "CA": "Canada",
    "VA": "Canada",
    "VY": "Canada",
    "VO": "Canada",
    "VK": "Australia",
    "ZL": "New Zealand",
    "DL": "Germany",
    "DA": "Germany",
    "DB": "Germany",
    "DF": "Germany",
    "DK": "Germany",
    "G": "England",
    "GX": "England",
    "GM": "Scotland",
    "GW": "Wales",
    "GI": "Northern Ireland",
    "GD": "Isle of Man",
    "GJ": "Jersey",
    "GU": "Guernsey",
    "F": "France",
    "I": "Italy",
    "EA": "Spain",
    "CT": "Portugal",
    "JA": "Japan",
    "JP": "Japan",
    "HL": "South Korea",
    "BV": "Taiwan",
    "BY": "China",
    "DU": "Philippines",
    "HS": "Thailand",
    "YB": "Indonesia",
    "9M": "Malaysia",
    "VU": "India",
    "4X": "Israel",
    "4Z": "Israel",
    "ZS": "South Africa",
    "PY": "Brazil",
    "PP": "Brazil",
    "LU": "Argentina",
    "CE": "Chile",
    "CX": "Uruguay",
    "OA": "Peru",
    "HK": "Colombia",
    "YV": "Venezuela",
    "XE": "Mexico",
    "HP": "Panama",
    "TI": "Costa Rica",
    "TG": "Guatemala",
    "TF": "Iceland",
    "LA": "Norway",
    "SM": "Sweden",
    "OH": "Finland",
    "OZ": "Denmark",
    "OY": "Faroe Islands",
    "OX": "Greenland",
    "ES": "Estonia",
    "YL": "Latvia",
    "LY": "Lithuania",
    "SP": "Poland",
    "OK": "Czech Republic",
    "OM": "Slovakia",
    "HA": "Hungary",
    "HG": "Hungary",
    "OE": "Austria",
    "HB": "Switzerland",
    "HB0": "Liechtenstein",
    "ON": "Belgium",
    "PA": "Netherlands",
    "PI": "Netherlands",
    "PB": "Netherlands",
    "PD": "Netherlands",
    "PE": "Netherlands",
    "LX": "Luxembourg",
    "YO": "Romania",
    "LZ": "Bulgaria",
    "SV": "Greece",
    "TA": "Turkey",
    "Z3": "North Macedonia",
    "ZA": "Albania",
    "9A": "Croatia",
    "S5": "Slovenia",
    "E7": "Bosnia & Herzegovina",
    "4O": "Montenegro",
    "YU": "Serbia",
    "CU": "Azores",
    "CT3": "Madeira",
    "EA8": "Canary Islands",
    "C3": "Andorra",
    "T7": "San Marino",
    "3A": "Monaco",
    "5B": "Cyprus",
    "EK": "Armenia",
    "4J": "Azerbaijan",
    "ER": "Moldova",
    "UR": "Ukraine",
}


@dataclass
class HuntedPark:
    reference: str
    park_name: str
    location: str
    dx_entity: str
    hasc: str
    first_qso_date: str
    qsos: int


@dataclass
class ActiveSpot:
    spot_id: int
    activator: str
    frequency_raw: str
    frequency_khz: float
    band: str
    mode: str
    reference: str
    park_name: str
    spot_time_raw: str
    spot_time_dt: Optional[datetime]
    spotter: str
    comments: str
    source: str
    location_desc: str
    grid4: str
    grid6: str
    latitude: Optional[float]
    longitude: Optional[float]
    count: int
    expire: int
    respots: List[dict] = field(default_factory=list)


@dataclass
class ComparedSpot:
    spot: ActiveSpot
    is_new: bool  # True if never hunted (or 0 QSOs)
    qsos_hunted: int
    hunted_park: Optional[HuntedPark] = None
    propagation: Optional[PropagationResult] = None
    p2p_my_park: Optional[str] = None  # Reference of operator's current park if in P2P mode

    @property
    def spot_evidence(self) -> Optional[SpotEvidence]:
        if self.propagation is not None:
            return self.propagation.spot_evidence
        return None

    @property
    def has_local_evidence(self) -> bool:
        ev = self.spot_evidence
        return bool(ev and (len(ev.local_spotters) > 0 or len(ev.local_state_mentions) > 0))

    @property
    def status_label(self) -> str:
        if self.is_new:
            return "NEW"
        return f"Hunted ({self.qsos_hunted})"

    @property
    def dx_percentage(self) -> int:
        if self.propagation is not None:
            return self.propagation.probability_pct
        return 0

    @property
    def dx_percentage_str(self) -> str:
        return f"{self.dx_percentage}%"

    @property
    def display_name(self) -> str:
        if self.spot.park_name:
            return self.spot.park_name
        if self.hunted_park and self.hunted_park.park_name:
            return self.hunted_park.park_name
        return "Unknown Park Name"

    @property
    def display_location(self) -> str:
        loc = self.spot.location_desc or ""
        ref = self.spot.reference or ""
        prefix = ref.split("-")[0].upper() if "-" in ref else ref.upper()

        dx_entity = self.hunted_park.dx_entity if (self.hunted_park and self.hunted_park.dx_entity) else ""

        # Determine if location is within United States (50 states)
        is_us = (prefix in ("US", "K") or dx_entity == "United States")

        if is_us:
            if loc:
                return loc
            if self.hunted_park and self.hunted_park.location:
                return self.hunted_park.location
            return prefix

        # For non-US locations, determine country name
        country = ""
        if dx_entity and dx_entity != loc:
            country = dx_entity
        elif prefix in POTA_PREFIX_TO_COUNTRY:
            country = POTA_PREFIX_TO_COUNTRY[prefix]
        else:
            for p_key, p_country in sorted(POTA_PREFIX_TO_COUNTRY.items(), key=lambda x: len(x[0]), reverse=True):
                if prefix.startswith(p_key):
                    country = p_country
                    break

        if loc and country:
            if country.lower() in loc.lower():
                return loc
            return f"{loc}, {country}"
        elif loc:
            return loc
        elif country:
            return country
        return prefix

    @property
    def frequency_mhz_str(self) -> str:
        if self.spot.frequency_khz <= 0:
            return self.spot.frequency_raw
        mhz = self.spot.frequency_khz / 1000.0
        if mhz >= 100:
            return f"{mhz:.4f} MHz"
        return f"{mhz:.3f} MHz"

    @property
    def age_minutes(self) -> float:
        """Returns elapsed minutes since the spot was posted."""
        if not self.spot.spot_time_dt:
            return 999.0
        now = datetime.now(timezone.utc)
        diff_sec = (now - self.spot.spot_time_dt).total_seconds()
        return max(0.0, diff_sec / 60.0)

    @property
    def decay_status(self) -> str:
        """
        Returns spot freshness decay status:
        - Fresh (< 15 mins)
        - Active (15 - 30 mins)
        - Aging (30 - 45 mins)
        - Expiring (> 45 mins)
        """
        age = self.age_minutes
        if age < 15.0:
            return "Fresh"
        elif age < 30.0:
            return "Active"
        elif age < 45.0:
            return "Aging"
        else:
            return "Expiring"

    @property
    def decay_color(self) -> str:
        """Returns color hex code for table styling based on spot age."""
        st = self.decay_status
        if st == "Fresh":
            return "#3fb950"  # Vibrant Green
        elif st == "Active":
            return "#58a6ff"  # Vibrant Blue/Cyan
        elif st == "Aging":
            return "#e3b341"  # Amber
        else:
            return "#db6d28"  # Orange/Muted

    @property
    def expire_mins_remaining(self) -> Optional[int]:
        """Calculates estimated minutes remaining before POTA drops/expires the spot."""
        if self.spot.expire and self.spot.expire > 0:
            return max(0, int(self.spot.expire // 60))
        return None

    @property
    def is_p2p_eligible(self) -> bool:
        """True if P2P mode is active and this spot is a different park than my park."""
        if not self.p2p_my_park:
            return False
        my_norm = normalize_ref(self.p2p_my_park)
        spot_norm = normalize_ref(self.spot.reference)
        return bool(my_norm and spot_norm and my_norm != spot_norm)

    @property
    def is_p2p_same_park(self) -> bool:
        """True if P2P mode is active and this spot is the same park as my park."""
        if not self.p2p_my_park:
            return False
        my_norm = normalize_ref(self.p2p_my_park)
        spot_norm = normalize_ref(self.spot.reference)
        return bool(my_norm and spot_norm and my_norm == spot_norm)

    @property
    def time_ago_str(self) -> str:
        if not self.spot.spot_time_dt:
            return self.spot.spot_time_raw
        now = datetime.now(timezone.utc)
        diff_sec = (now - self.spot.spot_time_dt).total_seconds()
        if diff_sec < 0:
            return "Just now"
        mins = int(diff_sec // 60)
        if mins < 1:
            return "Just now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m ago"


def parse_frequency_khz(freq_val) -> float:
    """Parses various frequency formats into float kHz."""
    if freq_val is None:
        return 0.0
    s = str(freq_val).strip()
    if not s:
        return 0.0
    # Strip non-numeric except decimal
    clean = re.sub(r"[^\d.]", "", s)
    if not clean:
        return 0.0
    try:
        val = float(clean)
        # Check if it was provided in Hz (e.g. 14054000) or MHz (e.g. 14.054)
        if val > 10000000:  # e.g. 14054000 Hz
            return val / 1000.0
        elif 0.1 <= val < 1000.0:  # e.g. 14.054 MHz
            if val < 60:  # 0.1 to 60 MHz
                return val * 1000.0
        return val
    except ValueError:
        return 0.0


def frequency_to_band(freq_khz: float) -> str:
    """Converts a frequency in kHz to ham radio band string."""
    if freq_khz <= 0:
        return "Unknown"
    for low, high, band_name in BAND_RANGES:
        if low <= freq_khz <= high:
            return band_name
    # Approximation if outside strict limits
    if 1800 <= freq_khz <= 2000:
        return "160m"
    if 3500 <= freq_khz <= 4000:
        return "80m"
    if 5000 <= freq_khz <= 5500:
        return "60m"
    if 7000 <= freq_khz <= 7350:
        return "40m"
    if 10100 <= freq_khz <= 10150:
        return "30m"
    if 14000 <= freq_khz <= 14350:
        return "20m"
    if 18068 <= freq_khz <= 18168:
        return "17m"
    if 21000 <= freq_khz <= 21450:
        return "15m"
    if 24890 <= freq_khz <= 24990:
        return "12m"
    if 28000 <= freq_khz <= 29700:
        return "10m"
    if 50000 <= freq_khz <= 54000:
        return "6m"
    if 144000 <= freq_khz <= 148000:
        return "2m"
    if 420000 <= freq_khz <= 450000:
        return "70cm"
    return "Other"


def parse_spot_datetime(iso_str: str) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def normalize_ref(ref: str) -> str:
    """Normalizes park reference e.g., 'us-1049' -> 'US-1049'."""
    if not ref:
        return ""
    return ref.strip().upper()


def load_hunter_csv(csv_path: str) -> Dict[str, HuntedPark]:
    """
    Reads hunter_parks.csv and returns a dictionary mapped by normalized Reference.
    CSV format expected: "DX Entity","Location","HASC","Reference","Park Name","First QSO Date","QSOs"
    """
    hunted_map: Dict[str, HuntedPark] = {}
    if not os.path.exists(csv_path):
        logger.warning("Hunter CSV file does not exist: %s", csv_path)
        return hunted_map

    with open(csv_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ref = ""
            name = ""
            loc = ""
            dx = ""
            hasc = ""
            first_qso = ""
            qsos = 1

            for k, v in row.items():
                if k is None or v is None:
                    continue
                k_clean = k.strip().lower()
                v_clean = v.strip()
                if k_clean == "reference":
                    ref = v_clean
                elif k_clean in ("park name", "name", "park"):
                    name = v_clean
                elif k_clean == "location":
                    loc = v_clean
                elif k_clean in ("dx entity", "dx", "entity"):
                    dx = v_clean
                elif k_clean == "hasc":
                    hasc = v_clean
                elif k_clean in ("first qso date", "first qso", "date"):
                    first_qso = v_clean
                elif k_clean in ("qsos", "qso", "count"):
                    try:
                        qsos = int(v_clean)
                    except ValueError:
                        qsos = 1

            norm = normalize_ref(ref)
            if norm:
                if norm in hunted_map:
                    hunted_map[norm].qsos += qsos
                else:
                    hunted_map[norm] = HuntedPark(
                        reference=norm,
                        park_name=name,
                        location=loc,
                        dx_entity=dx,
                        hasc=hasc,
                        first_qso_date=first_qso,
                        qsos=qsos,
                    )

    return hunted_map


def fetch_active_spots(timeout: int = 10) -> List[ActiveSpot]:
    """
    Queries live active spots from https://api.pota.app/spot/activator
    and aggregates detailed respot history from https://api.pota.app/spot.
    Returns list of ActiveSpot dataclass instances with associated respots.
    """
    # 1. Fetch activator summary spots
    req_act = urllib.request.Request(
        POTA_SPOT_API_URL,
        headers={
            "User-Agent": "POTA-Hunter-Comparator-GUI/1.0 (Ham Radio Desktop App)",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req_act, timeout=timeout) as response:
        raw_data = response.read().decode("utf-8")
        data = json.loads(raw_data)

    # 2. Fetch live individual spot stream for respot comments & history
    stream_by_act: Dict[str, List[dict]] = {}
    try:
        req_stream = urllib.request.Request(
            POTA_STREAM_API_URL,
            headers={
                "User-Agent": "POTA-Hunter-Comparator-GUI/1.0 (Ham Radio Desktop App)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req_stream, timeout=timeout) as response_stream:
            raw_stream = response_stream.read().decode("utf-8")
            stream_data = json.loads(raw_stream)
            if isinstance(stream_data, list):
                for s in stream_data:
                    if isinstance(s, dict):
                        act_key = str(s.get("activator") or "").strip().upper()
                        if act_key:
                            stream_by_act.setdefault(act_key, []).append(s)
    except Exception as e:
        logger.debug("Failed to fetch full POTA spot stream: %s", e)

    spots: List[ActiveSpot] = []
    if not isinstance(data, list):
        return spots

    for item in data:
        if not isinstance(item, dict):
            continue

        raw_freq = str(item.get("frequency") or "")
        freq_khz = parse_frequency_khz(raw_freq)
        band = frequency_to_band(freq_khz)
        mode = str(item.get("mode") or "").strip().upper()
        if not mode:
            mode = "OTHER"

        ref = normalize_ref(str(item.get("reference") or ""))
        park_name = str(item.get("name") or item.get("parkName") or "").strip()
        spot_time_raw = str(item.get("spotTime") or "")
        spot_time_dt = parse_spot_datetime(spot_time_raw)
        activator = str(item.get("activator") or "").strip().upper()
        spotter = str(item.get("spotter") or "").strip()
        comments = str(item.get("comments") or "").strip()

        lat = item.get("latitude")
        lon = item.get("longitude")
        try:
            lat = float(lat) if lat is not None else None
        except (ValueError, TypeError):
            lat = None
        try:
            lon = float(lon) if lon is not None else None
        except (ValueError, TypeError):
            lon = None

        # Get all historical respots for this activator
        act_respots = stream_by_act.get(activator, [])
        if not act_respots and (spotter or comments):
            act_respots = [
                {
                    "spotter": spotter,
                    "comments": comments,
                    "spotTime": spot_time_raw,
                    "frequency": raw_freq,
                    "mode": mode,
                }
            ]

        spot = ActiveSpot(
            spot_id=int(item.get("spotId") or 0),
            activator=activator,
            frequency_raw=raw_freq,
            frequency_khz=freq_khz,
            band=band,
            mode=mode,
            reference=ref,
            park_name=park_name,
            spot_time_raw=spot_time_raw,
            spot_time_dt=spot_time_dt,
            spotter=spotter,
            comments=comments,
            source=str(item.get("source") or "").strip(),
            location_desc=str(item.get("locationDesc") or "").strip(),
            grid4=str(item.get("grid4") or "").strip(),
            grid6=str(item.get("grid6") or "").strip(),
            latitude=lat,
            longitude=lon,
            count=int(item.get("count") or len(act_respots)),
            expire=int(item.get("expire") or 0),
            respots=act_respots,
        )
        spots.append(spot)

    return spots


def compare_active_spots(
    spots: List[ActiveSpot],
    hunted_map: Dict[str, HuntedPark],
    home_grid: str = DEFAULT_HOME_GRID,
    solar_weather: Optional[SolarWeather] = None,
    dt_utc: Optional[datetime] = None,
    resolver: Optional[CallsignResolver] = None,
    p2p_mode: bool = False,
    p2p_my_park: Optional[str] = None,
    p2p_grid: Optional[str] = None,
    tx_power_watts: float = DEFAULT_TX_POWER_WATTS,
    antenna_type: str = DEFAULT_ANTENNA_TYPE,
    op_call: str = "",
    lightning_summary: Optional[RegionalLightningSummary] = None,
) -> List[ComparedSpot]:
    """
    Compares active spots against hunted parks and computes HF/VHF propagation
    probabilities along with spotter evidence, station link budget,
    and regional lightning QRN noise.
    Leverages multi-core CPU parallelization to evaluate spots.
    """
    # In P2P mode, use portable field grid if provided
    effective_grid = p2p_grid.strip().upper() if (p2p_mode and p2p_grid and p2p_grid.strip()) else home_grid.strip().upper()
    effective_park = p2p_my_park.strip().upper() if (p2p_mode and p2p_my_park and p2p_my_park.strip()) else None

    home_lat, home_lon = maidenhead_to_latlon(effective_grid)
    if home_lat is None or home_lon is None:
        home_lat, home_lon = 38.3125, -81.7083  # Default EM98dh

    if solar_weather is None:
        solar_weather = SolarWeather()
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    if resolver is None:
        resolver = CallsignResolver()
    if lightning_summary is None and home_lat is not None and home_lon is not None:
        lightning_summary = fetch_regional_lightning_summary(home_lat, home_lon)

    if not spots:
        return []

    def evaluate_spot(spot: ActiveSpot) -> ComparedSpot:
        hunted = hunted_map.get(spot.reference)
        is_new = (hunted is None or hunted.qsos == 0)
        qsos_hunted = 0 if is_new else hunted.qsos

        # Parse empirical evidence from all respots & main spot comment
        all_respots = list(spot.respots or [])
        if spot.comments:
            has_main = any(str(r.get("comments") or "").strip() == spot.comments for r in all_respots)
            if not has_main:
                all_respots.append({
                    "spotter": spot.spotter,
                    "comments": spot.comments,
                    "spotTime": spot.spot_time_raw,
                })

        evidence = parse_spot_evidence(
            all_respots,
            home_lat=home_lat,
            home_lon=home_lon,
            activator_call=spot.activator,
            op_call=op_call,
            user_grid=effective_grid,
            resolver=resolver,
            dt_utc=dt_utc,
        )

        # Check if same park in P2P mode
        is_same_park = False
        if effective_park and spot.reference:
            is_same_park = (normalize_ref(effective_park) == normalize_ref(spot.reference))

        # Calculate propagation probability and path metrics
        target_grid = spot.grid6 or spot.grid4 or None
        prop = calculate_qso_probability(
            home_lat=home_lat,
            home_lon=home_lon,
            target_lat=spot.latitude,
            target_lon=spot.longitude,
            target_grid=target_grid,
            freq_khz=spot.frequency_khz,
            band=spot.band,
            mode=spot.mode,
            solar_weather=solar_weather,
            dt_utc=dt_utc,
            spot_evidence=evidence,
            tx_power_watts=tx_power_watts,
            antenna_type=antenna_type,
            is_same_park=is_same_park,
            lightning_summary=lightning_summary,
        )

        return ComparedSpot(
            spot=spot,
            is_new=is_new,
            qsos_hunted=qsos_hunted,
            hunted_park=hunted,
            propagation=prop,
            p2p_my_park=effective_park,
        )

    # Multi-core CPU parallelization: utilize maximum CPU capacity
    cpu_cores = os.cpu_count() or 4
    max_workers = min(32, max(4, cpu_cores * 2))

    if len(spots) <= 4:
        return [evaluate_spot(s) for s in spots]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(evaluate_spot, spots))

    return results


PARK_CACHE_FILE = os.path.expanduser("~/.pota_park_cache.json")


def load_park_cache() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(PARK_CACHE_FILE):
        try:
            with open(PARK_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_park_cache(cache: Dict[str, Dict[str, Any]]):
    try:
        with open(PARK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def fetch_park_info(
    reference: str, active_spots: Optional[List[ActiveSpot]] = None
) -> Optional[Dict[str, Any]]:
    """
    Looks up park details (name, grid6, grid4, lat, lon) by reference.
    1. Checks active spots in memory.
    2. Checks ~/.pota_park_cache.json.
    3. Fetches from https://api.pota.app/park/{ref}.
    """
    if not reference or not isinstance(reference, str):
        return None
    ref = normalize_ref(reference)

    # 1. Active spots
    if active_spots:
        for s in active_spots:
            if normalize_ref(s.reference) == ref:
                grid = s.grid6 or s.grid4
                if not grid and s.latitude is not None and s.longitude is not None:
                    grid = latlon_to_maidenhead(s.latitude, s.longitude)
                if grid:
                    return {
                        "reference": ref,
                        "name": s.park_name,
                        "grid": grid,
                        "grid4": s.grid4 or grid[:4],
                        "grid6": s.grid6 or grid,
                        "latitude": s.latitude,
                        "longitude": s.longitude,
                        "locationDesc": s.location_desc,
                    }

    # 2. Local cache
    cache = load_park_cache()
    if ref in cache:
        return cache[ref]

    # 3. POTA Park API
    url = f"https://api.pota.app/park/{ref}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "POTA-Hunter-Comparator/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            lat = data.get("latitude")
            lon = data.get("longitude")
            grid6 = data.get("grid6")
            grid4 = data.get("grid4")
            grid = grid6 or grid4
            if not grid and lat is not None and lon is not None:
                grid = latlon_to_maidenhead(float(lat), float(lon))

            park_info = {
                "reference": ref,
                "name": data.get("name") or "",
                "grid": grid or "",
                "grid4": grid4 or (grid[:4] if grid else ""),
                "grid6": grid6 or (grid if grid and len(grid) >= 6 else ""),
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "locationDesc": data.get("locationDesc") or "",
            }
            cache[ref] = park_info
            save_park_cache(cache)
            return park_info
    except Exception as e:
        logger.debug(f"Failed to lookup park {ref} from POTA API: {e}")
        return None

