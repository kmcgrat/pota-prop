"""
POTA HF/VHF Propagation & QSO Probability Engine
Models amateur radio ionospheric skywave propagation with multi-layer electron density profiles,
multi-hop ray tracing (1E, 2E, 1F2, 2F2, 3F2, 4F2), launch elevation angles, skip-zone cutoff,
E-layer screening, ITU-R P.372 atmospheric noise with real-time regional lightning (QRN) integration,
NOAA space weather (SFI, K-index, A-index, GOES X-ray flares), and spot intelligence.
"""

import json
import logging
import math
import os
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from meteor_engine import MeteorActivity, get_current_meteor_activity
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from drap_engine import get_drap_attenuation

logger = logging.getLogger(__name__)

NOAA_10CM_FLUX_URL = "https://services.swpc.noaa.gov/products/summary/10cm-flux.json"
NOAA_K_INDEX_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
NOAA_A_INDEX_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-a-index.json"
NOAA_GOES_XRAY_URL = "https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json"
NOAA_HPI_URL = "https://services.swpc.noaa.gov/text/aurora-nowcast-hemi-power.txt"
NOAA_SSN_URL = "https://services.swpc.noaa.gov/text/daily-solar-indices.txt"
NOAA_3DAY_FORECAST_URL = "https://services.swpc.noaa.gov/text/3-day-forecast.txt"
NOAA_HPI_URL = "https://services.swpc.noaa.gov/text/aurora-nowcast-hemi-power.txt"
NOAA_SSN_URL = "https://services.swpc.noaa.gov/text/daily-solar-indices.txt"

DEFAULT_HOME_GRID = "EM98dh"
EARTH_RADIUS_KM = 6371.0


@dataclass
class SolarWeather:
    sfi: float = 145.0          # Solar Flux Index (10.7cm flux in sfu)
    ssn: int = 100              # Sunspot Number
    k_index: float = 2.0        # Planetary K-index (0 to 9)
    k_forecast: str = "N/A"     # 3-Day K-Index Forecast
    a_index: float = 8.0        # Planetary A-index (0 to 400 linear 24h daily index)
    aurora_hpi: float = 15.0    # Northern Hemispheric Power Index in GW
    xray_flux: float = 1e-7     # GOES 0.1-0.8nm X-ray flux in W/m^2
    xray_class: str = "B1.0"    # Flare class (e.g. C2.4, M1.5, X2.1)
    radio_blackout_scale: str = "R0 (Normal)"  # NOAA R-scale (R0 to R5)
    flare_penalty: int = 0      # Score penalty during active flares (0 to -50)
    condition: str = "Normal"   # Quiet, Unsettled, Active, Minor Storm, Major Storm
    updated_at: str = "Cached"
    source: str = "NOAA SWPC / GOES"
    meteor_activity: Optional[MeteorActivity] = None

    @property
    def storm_condition(self) -> str:
        return self.condition

    @property
    def flare_status(self) -> str:
        return f"{self.xray_class} ({self.radio_blackout_scale})"

    def get_ssn_assessment(self) -> Tuple[str, str, str]:
        """Returns assessment for Sunspot Number (SSN)."""
        ssn = self.ssn
        if ssn >= 100:
            return (str(ssn), "#3fb950", "High sunspot activity drives robust F2 layer ionization.")
        elif ssn >= 50:
            return (str(ssn), "#d29922", "Moderate sunspot activity. Good 20m openings.")
        else:
            return (str(ssn), "#8b949e", "Low sunspot activity. Upper HF bands may be closed.")

    def get_hpi_assessment(self) -> Tuple[str, str, str]:
        """Returns assessment for Auroral Hemispheric Power Index (HPI)."""
        hpi = self.aurora_hpi
        if hpi < 20:
            return (f"{hpi} GW (Quiet)", "#3fb950", "Quiet auroral oval. Low absorption at high latitudes.")
        elif hpi < 40:
            return (f"{hpi} GW (Active)", "#d29922", "Active auroral oval. Moderate D-layer absorption for polar paths.")
        elif hpi < 60:
            return (f"{hpi} GW (Storm)", "#f85149", "Geomagnetic storming. High auroral absorption and flutter fading on polar paths.")
        else:
            return (f"{hpi} GW (Severe)", "#ff2a55", "Severe storming. Blackout conditions for high-latitude HF propagation.")

    def get_sfi_assessment(self) -> Tuple[str, str, str]:
        """Returns (rating_label, hex_color, brief_explanation) for Solar Flux Index."""
        val = self.sfi
        if val >= 150:
            return (
                "Excellent (High)",
                "#3fb950",
                f"SFI {int(val)} sfu: High solar UV/EUV radiation strongly ionizes F2 layer. Higher MUFs enable strong long-distance DX across 10m, 12m, 15m, 17m, and 20m.",
            )
        elif val >= 100:
            return (
                "Good (Normal)",
                "#7ee787",
                f"SFI {int(val)} sfu: Solid F2 layer ionization supporting reliable daytime propagation on 20m–15m with occasional 10m/12m openings.",
            )
        elif val >= 80:
            return (
                "Fair (Moderate)",
                "#d29922",
                f"SFI {int(val)} sfu: Moderate ionization. 40m, 30m, and 20m are primary bands; higher frequencies (15m–10m) marginal.",
            )
        else:
            return (
                "Poor (Low)",
                "#f85149",
                f"SFI {int(val)} sfu: Weak F2 ionization. Low MUFs; upper bands (15m–10m) closed; daytime operations limited to 20m and below.",
            )

    def get_k_assessment(self) -> Tuple[str, str, str]:
        """Returns (rating_label, hex_color, brief_explanation) for 3-hour Planetary K-index."""
        k = int(round(self.k_index))
        if k <= 1:
            return (
                f"Kp={k} (Quiet)",
                "#3fb950",
                "Geomagnetic field is quiet and stable. Minimal auroral absorption; low ionospheric noise floor; excellent multi-hop HF circuits.",
            )
        elif k <= 3:
            return (
                f"Kp={k} (Unsettled)",
                "#7ee787",
                "Normal baseline geomagnetic conditions. F2 layer stable; standard path attenuation on all bands.",
            )
        elif k == 4:
            return (
                f"Kp={k} (Active)",
                "#d29922",
                "Geomagnetic disturbance active. Polar and trans-auroral paths exhibit signal flutter, rapid fading (QSB), and depressed MUFs.",
            )
        elif k == 5:
            return (
                f"Kp={k} (G1 Minor Storm)",
                "#db6d28",
                "NOAA G1 Storm: High-latitude HF propagation degraded; auroral absorption begins; significant signal flutter on polar paths.",
            )
        elif k == 6:
            return (
                f"Kp={k} (G2 Moderate Storm)",
                "#f0883e",
                "NOAA G2 Storm: High-latitude HF blackout; auroral flutter and absorption spreads to mid-latitudes; low-band noise surge.",
            )
        elif k == 7:
            return (
                f"Kp={k} (G3 Strong Storm)",
                "#da3633",
                "NOAA G3 Storm: Severe geomagnetic storm. Degraded HF across wide latitudes; intermittent radio blackouts; unstable reflections.",
            )
        elif k == 8:
            return (
                f"Kp={k} (G4 Severe Storm)",
                "#f85149",
                "NOAA G4 Storm: Deep HF radio blackout on polar/auroral paths; severe degradation spreading towards mid/equatorial paths.",
            )
        else:
            return (
                f"Kp={k} (G5 Extreme Storm)",
                "#ff2a55",
                "NOAA G5 Storm: Extreme geomagnetic storm. Complete HF radio blackouts across vast areas of the globe lasting for hours/days.",
            )

    def get_a_assessment(self) -> Tuple[str, str, str]:
        """Returns (rating_label, hex_color, brief_explanation) for 24-hour Planetary A-index."""
        a = int(round(self.a_index))
        if a <= 7:
            return (
                f"Ap={a} (Quiet)",
                "#3fb950",
                "24-hour daily geomagnetic activity is very quiet. Steady ionosphere supporting long-range DX.",
            )
        elif a <= 15:
            return (
                f"Ap={a} (Unsettled)",
                "#7ee787",
                "24-hour baseline unsettled. Typical everyday propagation conditions with nominal absorption.",
            )
        elif a <= 29:
            return (
                f"Ap={a} (Active)",
                "#d29922",
                "24-hour active geomagnetic disturbance. Sustained F-layer instability and elevated polar path absorption.",
            )
        elif a <= 49:
            return (
                f"Ap={a} (Minor Storm)",
                "#db6d28",
                "Sustained minor geomagnetic storm over past 24h. Noticeable reduction in SNR and lower reliable MUFs.",
            )
        elif a <= 99:
            return (
                f"Ap={a} (Major Storm)",
                "#da3633",
                "Major daily geomagnetic storm. High absorption, erratic skip distances, and deep multi-path fading.",
            )
        else:
            return (
                f"Ap={a} (Severe Storm)",
                "#ff2a55",
                "Severe multi-day geomagnetic disruption with widespread HF degradation and propagation collapse.",
            )

    def get_xray_assessment(self) -> Tuple[str, str, str]:
        """Returns (rating_label, hex_color, brief_explanation) for Solar X-Ray Flare & R-Scale."""
        cls = self.xray_class.upper()
        if cls.startswith("X"):
            return (
                f"{self.xray_class} ({self.radio_blackout_scale})",
                "#ff2a55",
                "GOES X-Class Solar Flare: Intense X-ray burst causing major D-layer ionization and sudden ionospheric disturbance (SID). Wide-area daylight Shortwave Fadeout.",
            )
        elif cls.startswith("M"):
            return (
                f"{self.xray_class} ({self.radio_blackout_scale})",
                "#e06c3a",
                "GOES M-Class Solar Flare: Moderate solar flare producing localized daylight D-layer absorption and signal attenuation on lower/mid HF bands.",
            )
        elif cls.startswith("C"):
            return (
                f"{self.xray_class} ({self.radio_blackout_scale})",
                "#d29922" if self.flare_penalty < 0 else "#7ee787",
                "GOES C-Class Solar Flare: Low to moderate flare activity; minor D-layer ionization with minimal impact on HF communications.",
            )
        else:
            return (
                f"{self.xray_class} ({self.radio_blackout_scale})",
                "#3fb950",
                "Background solar X-ray emission. Zero D-layer flare absorption on sunlit hemisphere.",
            )

    def get_overall_assessment(self) -> Tuple[str, str, str]:
        """Returns (overall_status, hex_color, operational_guidance) synthesizing all parameters."""
        k = self.k_index
        a = self.a_index
        sfi = self.sfi
        cls = self.xray_class.upper()
        hpi = self.aurora_hpi

        forecast_msg = ""
        if self.k_forecast != "N/A":
            try:
                kf = float(self.k_forecast)
                if kf >= 5:
                    forecast_msg = f"<br/><br/><b>Outlook (Next 24-48 Hours):</b> The planetary K-index is forecast to rise to {int(kf)}, indicating an impending major geomagnetic storm. Expect degrading conditions, increased signal absorption, and a suppressed F2 layer."
                elif kf == 4:
                    forecast_msg = f"<br/><br/><b>Outlook (Next 24-48 Hours):</b> The planetary K-index is forecast to reach {int(kf)}, leading to unsettled geomagnetic conditions. Watch for potential high-latitude fading and brief periods of noise."
                elif kf <= 3:
                    forecast_msg = f"<br/><br/><b>Outlook (Next 24-48 Hours):</b> Conditions are forecast to remain relatively stable with a quiet K-index of {int(kf)}."
            except ValueError:
                pass

        if k >= 6 or a >= 50 or cls.startswith("X") or hpi > 60 or self.radio_blackout_scale.startswith(("R3", "R4", "R5")):
            return (
                "Storm Blackout / Highly Degraded",
                "#f85149",
                f"<b>Current Conditions:</b> A severe space weather event is actively occurring. A major disturbance (such as a Geomagnetic Storm, X-Class Flare, or Intense Auroral Power) is strongly ionizing the lower D-layer while severely depleting the upper F2-layer. You will experience high signal absorption, severe flutter fading, significantly lower maximum usable frequencies (MUFs), and potential total radio blackouts on sunlit or polar circuits.{forecast_msg}",
            )
        elif k >= 4 or a >= 30 or cls.startswith("M") or hpi > 35 or self.radio_blackout_scale.startswith(("R1", "R2")):
            return (
                "Unsettled / Active Storm Disturbance",
                "#db6d28",
                f"<b>Current Conditions:</b> An active space weather disturbance is in progress. Elevated geomagnetic or solar flare activity is actively increasing atmospheric noise and D-layer signal absorption. High-latitude and trans-polar paths are likely experiencing severe flutter fading and elevated path attenuation. Lower HF bands will be particularly noisy and difficult to use.{forecast_msg}",
            )
        elif sfi >= 120 and k <= 3 and a <= 15 and hpi <= 20:
            return (
                "Quiet / Excellent HF Conditions",
                "#3fb950",
                f"<b>Current Conditions:</b> Optimal space weather is occurring right now. High solar flux is strongly ionizing the F2-layer, raising maximum usable frequencies across the globe. Meanwhile, quiet geomagnetic and auroral conditions are keeping signal absorption and background noise extremely low. This combination strongly supports excellent global DX and stable multi-hop propagation.{forecast_msg}",
            )
        else:
            return (
                "Fair / Moderate Conditions",
                "#d29922",
                f"<b>Current Conditions:</b> Moderate HF conditions are currently present. A nominal solar flux is sustaining the standard ionospheric layers with a generally stable auroral boundary. Lower frequency bands may suffer from typical daytime D-layer absorption, but higher bands should consistently support regional and some global DX paths.{forecast_msg}",
            )

    def format_tooltip_html(self) -> str:
        """Formats a rich HTML tooltip with NOAA SWPC categories, color codes, and explanations."""
        ssn_lbl, ssn_col, ssn_desc = self.get_ssn_assessment()
        sfi_lbl, sfi_col, sfi_desc = self.get_sfi_assessment()
        k_lbl, k_col, k_desc = self.get_k_assessment()
        a_lbl, a_col, a_desc = self.get_a_assessment()
        xr_lbl, xr_col, xr_desc = self.get_xray_assessment()
        hpi_lbl, hpi_col, hpi_desc = self.get_hpi_assessment()
        ov_lbl, ov_col, ov_guid = self.get_overall_assessment()

        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 12px; color: #e6edf3; line-height: 1.4;'>")
        lines.append(
            f"<div style='font-size: 14px; font-weight: bold; color: {ov_col}; margin-bottom: 6px;'>"
            f"NOAA Space Weather & Ionospheric Conditions: {ov_lbl}</div>"
        )
        lines.append(f"<div style='color: #8b949e; margin-bottom: 8px;'>{ov_guid}</div>")

        lines.append("<table style='font-size: 11px; color: #c9d1d9; border-collapse: collapse; width: 100%;'>")

        # SSN Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>Sunspot Number:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {ssn_col}; font-weight: bold;'>{ssn_lbl}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{ssn_desc}</td>"
            f"</tr>"
        )

        # SFI Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>Solar Flux (SFI):</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {sfi_col}; font-weight: bold;'>{int(self.sfi)} sfu ({sfi_lbl})</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{sfi_desc}</td>"
            f"</tr>"
        )

        # K-Index Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>Planetary K-Index:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {k_col}; font-weight: bold;'>{k_lbl}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{k_desc}</td>"
            f"</tr>"
        )

        # Forecast K-Index Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>3-Day Forecast K:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: #c9d1d9; font-weight: bold;'>{self.k_forecast}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>Expected maximum K-index over the next 3 days.</td>"
            f"</tr>"
        )

        # A-Index Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>Planetary A-Index:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {a_col}; font-weight: bold;'>{a_lbl}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{a_desc}</td>"
            f"</tr>"
        )

        # Solar Flare / X-Ray Row
        lines.append(
            f"<tr style='border-bottom: 1px solid #30363d;'>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>GOES Solar Flare:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {xr_col}; font-weight: bold;'>{xr_lbl}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{xr_desc}</td>"
            f"</tr>"
        )

        # HPI Row
        lines.append(
            f"<tr>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><b>Aurora HPI:</b></td>"
            f"<td style='padding: 4px 8px 4px 0; vertical-align: top; white-space: nowrap;'><span style='color: {hpi_col}; font-weight: bold;'>{hpi_lbl}</span></td>"
            f"<td style='padding: 4px 0; color: #8b949e;'>{hpi_desc}</td>"
            f"</tr>"
        )

        lines.append("</table>")

        lines.append(
            "<div style='margin-top: 8px; font-size: 10px; color: #8b949e; border-top: 1px solid #30363d; padding-top: 4px;'>"
            "Source: NOAA Space Weather Prediction Center (SWPC) & GOES-16/18 Solar Telemetry | Updated in real-time"
            "</div>"
        )
        lines.append("</div>")
        return "".join(lines)


@dataclass
class CallsignLocation:
    callsign: str
    state: Optional[str] = None
    grid: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    name: Optional[str] = None
    distance_miles: Optional[float] = None
    is_local_area: bool = False
    method: str = "POTA Spot"
    snr: Optional[float] = None
    age_mins: Optional[float] = None


@dataclass
class SpotEvidence:
    total_respots: int = 0
    recent_respots_45m: int = 0
    spotters: List[str] = field(default_factory=list)
    local_spotters: List[CallsignLocation] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)
    local_state_mentions: List[str] = field(default_factory=list)
    signal_reports: List[str] = field(default_factory=list)
    max_rbn_snr_db: Optional[float] = None
    empirical_boost_pct: int = 0
    evidence_summary: str = ""
    op_land_desc: str = "8-Land / Near WV"
    is_qrt: bool = False
    has_psk_reporter_decode: bool = False
    regional_boost: int = 0
    regional_summary: str = ""


@dataclass
class RegionalPathMatrix:
    openings: Dict[Tuple[str, str], List[Tuple[float, str, Optional[float], bool]]] = field(default_factory=dict)


@dataclass
class PropagationResult:
    probability_pct: int
    distance_km: float
    distance_miles: float
    bearing_deg: float
    path_type: str
    path_summary: str
    muf_est_mhz: float
    is_grayline: bool
    solar_info: SolarWeather
    spot_evidence: Optional[SpotEvidence] = None
    tx_power_watts: float = 100.0
    antenna_type: str = "EFHW"
    antenna_gain_dbi: float = 0.0
    station_offset_db: float = 0.0
    # Link budget, ray mode & ITU-R P.372 / QRN metrics
    predicted_snr_db: Optional[float] = None
    circuit_reliability_pct: Optional[int] = None
    ray_mode: str = "1F2"
    takeoff_angle_deg: float = 0.0
    hop_count: int = 1
    path_loss_db: float = 0.0
    noise_floor_dbw: float = -140.0
    qrn_surge_db: float = 0.0
    drap_loss_db: float = 0.0
    lightning_summary: Optional[Any] = None
    profile: Optional['IonosphericProfile'] = None
    ray_candidate: Optional['RayHopCandidate'] = None


@dataclass
class BandNoiseBreakdown:
    """Detailed ITU-R P.372 and real-time lightning noise figure breakdown for a single amateur band."""
    band: str
    freq_mhz: float
    f_atm_base_db: float
    qrn_surge_db: float
    f_atm_total_db: float
    f_gal_db: float
    f_man_db: float
    f_a_total_db: float
    noise_power_dbm: float
    s_units_val: float
    s_units_label: str
    dominant_source: str
    is_elevated_qrn: bool = False


# -------------------------------------------------------------
# Station Transmitter Power Output & Antenna Characteristics
# -------------------------------------------------------------
DEFAULT_TX_POWER_WATTS = 100.0
DEFAULT_ANTENNA_TYPE = "EFHW"

ANTENNA_PRESETS: Dict[str, Dict[str, Any]] = {
    "EFHW": {
        "key": "EFHW",
        "name": "EFHW",
        "hf_gain_db": 2.5,
        "vhf_gain_db": 1.5,
        "nvis_gain_db": 3.8,
        "desc": "Resonant multi-band wire, standard POTA baseline (+2.5 dBi mid-angle)",
    },
    "DIPOLE": {
        "key": "DIPOLE",
        "name": "Dipole / Inverted-V",
        "hf_gain_db": 4.5,
        "vhf_gain_db": 1.5,
        "nvis_gain_db": 6.5,
        "desc": "Resonant dipole/inverted-V, exceptional NVIS (+6.5 dBi) & broadside regional skywave",
    },
    "VERTICAL": {
        "key": "VERTICAL",
        "name": "Vertical (1/4λ / GP)",
        "hf_gain_db": 4.5,
        "vhf_gain_db": 2.2,
        "nvis_gain_db": -6.0,
        "desc": "Low-angle DX specialist (+4.5 dBi @ 10°-18°); deep overhead null for NVIS",
    },
    "BEAM": {
        "key": "BEAM",
        "name": "Beam / Yagi / Hexbeam",
        "hf_gain_db": 9.5,
        "vhf_gain_db": 9.5,
        "nvis_gain_db": 3.5,
        "desc": "High directional gain (+9.5 dBi low-angle lobe); massive DX and mid-range boost",
    },
    "RANDOM_WIRE": {
        "key": "RANDOM_WIRE",
        "name": "Random Wire (9:1 UnUn)",
        "hf_gain_db": -2.5,
        "vhf_gain_db": -3.5,
        "nvis_gain_db": -1.5,
        "desc": "Non-resonant end-fed with unun transformer loss and ground return loss (-2.5 dBi)",
    },
    "MAG_LOOP": {
        "key": "MAG_LOOP",
        "name": "Magnetic Loop",
        "hf_gain_db": -2.0,
        "vhf_gain_db": -5.0,
        "nvis_gain_db": -5.5,
        "desc": "Compact high-Q tuned loop, portable with noise reduction (-2 to -6 dBi)",
    },
    "VHF_COLLINEAR": {
        "key": "VHF_COLLINEAR",
        "name": "VHF/UHF Collinear Base",
        "hf_gain_db": -3.0,
        "vhf_gain_db": 7.0,
        "nvis_gain_db": -4.0,
        "desc": "High-gain base vertical extending 2m/70cm line-of-sight (+7.0 dBi)",
    },
    "RUBBER_DUCK": {
        "key": "RUBBER_DUCK",
        "name": "Rubber Duck / HT",
        "hf_gain_db": -22.0,
        "vhf_gain_db": -6.5,
        "nvis_gain_db": -22.0,
        "desc": "Handheld HT rubber duck — extreme compromise on HF (-22 dBi), weak VHF",
    },
}

POWER_PRESETS: List[Tuple[str, float]] = [
    ("5W", 5.0),
    ("10W", 10.0),
    ("20W", 20.0),
    ("50W", 50.0),
    ("100W", 100.0),
    ("500W", 500.0),
    ("1500W", 1500.0),
]

US_STATE_NEIGHBORS: Dict[str, Set[str]] = {
    "AL": {"TN", "GA", "FL", "MS"},
    "AK": set(),
    "AZ": {"CA", "NV", "UT", "NM"},
    "AR": {"MO", "TN", "MS", "LA", "TX", "OK"},
    "CA": {"OR", "NV", "AZ"},
    "CO": {"WY", "NE", "KS", "OK", "NM", "UT"},
    "CT": {"NY", "MA", "RI"},
    "DE": {"PA", "MD", "NJ"},
    "FL": {"GA", "AL"},
    "GA": {"TN", "NC", "SC", "FL", "AL"},
    "HI": set(),
    "ID": {"WA", "OR", "NV", "UT", "WY", "MT"},
    "IL": {"WI", "IA", "MO", "KY", "IN"},
    "IN": {"MI", "IL", "KY", "OH"},
    "IA": {"MN", "SD", "NE", "MO", "IL", "WI"},
    "KS": {"NE", "MO", "OK", "CO"},
    "KY": {"IN", "OH", "WV", "VA", "TN", "MO", "IL"},
    "LA": {"AR", "MS", "TX"},
    "ME": {"NH"},
    "MD": {"PA", "DE", "VA", "WV"},
    "MA": {"NH", "VT", "RI", "CT", "NY"},
    "MI": {"OH", "IN", "WI"},
    "MN": {"WI", "IA", "SD", "ND"},
    "MS": {"TN", "AL", "LA", "AR"},
    "MO": {"IA", "IL", "KY", "TN", "AR", "OK", "KS", "NE"},
    "MT": {"ID", "WY", "SD", "ND"},
    "NE": {"SD", "IA", "MO", "KS", "CO", "WY"},
    "NV": {"OR", "ID", "UT", "AZ", "CA"},
    "NH": {"ME", "VT", "MA"},
    "NJ": {"NY", "PA", "DE"},
    "NM": {"CO", "OK", "TX", "AZ"},
    "NY": {"VT", "MA", "CT", "NJ", "PA"},
    "NC": {"VA", "TN", "GA", "SC"},
    "ND": {"MN", "SD", "MT"},
    "OH": {"MI", "IN", "KY", "WV", "PA"},
    "OK": {"KS", "MO", "AR", "TX", "NM", "CO"},
    "OR": {"WA", "ID", "NV", "CA"},
    "PA": {"NY", "NJ", "DE", "MD", "WV", "OH"},
    "RI": {"MA", "CT"},
    "SC": {"NC", "GA"},
    "SD": {"ND", "MN", "IA", "NE", "WY", "MT"},
    "TN": {"KY", "VA", "NC", "GA", "AL", "MS", "AR", "MO"},
    "TX": {"NM", "OK", "AR", "LA"},
    "UT": {"ID", "WY", "CO", "NM", "AZ", "NV"},
    "VT": {"NH", "MA", "NY"},
    "VA": {"MD", "WV", "KY", "NC"},
    "WA": {"OR", "ID"},
    "WV": {"OH", "PA", "MD", "VA", "KY"},
    "WI": {"MN", "IA", "IL", "MI"},
    "WY": {"MT", "SD", "NE", "CO", "UT", "ID"},
    "ON": {"QC", "MB", "NY", "MI", "OH"},
    "QC": {"ON", "NB", "NY", "VT", "ME"},
    "BC": {"AB", "WA", "ID"},
    "AB": {"BC", "SK", "MT"},
}

US_STATE_CALL_DISTRICT: Dict[str, str] = {
    "CT": "1", "MA": "1", "ME": "1", "NH": "1", "RI": "1", "VT": "1",
    "NJ": "2", "NY": "2",
    "DE": "3", "MD": "3", "PA": "3",
    "AL": "4", "FL": "4", "GA": "4", "KY": "4", "NC": "4", "SC": "4", "TN": "4", "VA": "4",
    "AR": "5", "LA": "5", "MS": "5", "NM": "5", "OK": "5", "TX": "5",
    "CA": "6",
    "AZ": "7", "ID": "7", "MT": "7", "NV": "7", "OR": "7", "UT": "7", "WA": "7", "WY": "7",
    "MI": "8", "OH": "8", "WV": "8",
    "IL": "9", "IN": "9", "WI": "9",
    "CO": "0", "IA": "0", "KS": "0", "MN": "0", "MO": "0", "NE": "0", "ND": "0", "SD": "0",
    "AK": "KL7", "HI": "KH6", "PR": "KP4",
    "ON": "VE3", "QC": "VE2", "BC": "VE7", "AB": "VE6", "MB": "VE4", "SK": "VE5",
}

US_STATE_BOUNDS = [
    ("WV", 37.2, 40.6, -82.7, -77.7),
    ("MA", 41.2, 42.9, -73.5, -69.9),
    ("CA", 32.5, 42.0, -124.4, -114.1),
    ("TX", 25.8, 36.5, -106.6, -93.5),
    ("FL", 24.5, 31.0, -87.6, -80.0),
    ("NY", 40.5, 45.0, -79.8, -71.8),
    ("PA", 39.7, 42.3, -80.5, -74.7),
    ("OH", 38.4, 42.0, -84.8, -80.5),
    ("VA", 36.5, 39.5, -83.7, -75.2),
    ("NC", 33.8, 36.6, -84.3, -75.4),
    ("SC", 32.0, 35.2, -83.4, -78.5),
    ("GA", 30.4, 35.0, -85.6, -80.8),
    ("TN", 35.0, 36.7, -90.3, -81.6),
    ("KY", 36.5, 39.1, -89.6, -81.9),
    ("IN", 37.8, 41.8, -88.1, -84.8),
    ("IL", 37.0, 42.5, -91.5, -87.5),
    ("MI", 41.7, 48.3, -90.4, -82.4),
    ("WI", 42.5, 47.1, -92.9, -86.8),
    ("MN", 43.5, 49.4, -97.2, -89.5),
    ("MO", 36.0, 40.6, -95.8, -89.1),
    ("IA", 40.4, 43.5, -96.6, -90.1),
    ("AR", 33.0, 36.5, -94.6, -89.6),
    ("LA", 28.9, 33.0, -94.0, -88.8),
    ("MS", 30.2, 35.0, -91.6, -88.1),
    ("AL", 30.2, 35.0, -88.5, -84.9),
    ("OK", 33.6, 37.0, -103.0, -94.4),
    ("KS", 37.0, 40.0, -102.1, -94.6),
    ("NE", 40.0, 43.0, -104.1, -95.3),
    ("SD", 42.5, 45.9, -104.1, -96.4),
    ("ND", 45.9, 49.0, -104.1, -96.6),
    ("CO", 37.0, 41.0, -109.1, -102.0),
    ("NM", 31.3, 37.0, -109.1, -103.0),
    ("AZ", 31.3, 37.0, -114.8, -109.0),
    ("UT", 37.0, 42.0, -114.1, -109.0),
    ("NV", 35.0, 42.0, -120.0, -114.0),
    ("WY", 41.0, 45.0, -111.1, -104.1),
    ("MT", 44.4, 49.0, -116.1, -104.0),
    ("ID", 42.0, 49.0, -117.2, -111.0),
    ("WA", 45.5, 49.0, -124.8, -116.9),
    ("OR", 42.0, 46.3, -124.6, -116.5),
    ("ME", 43.1, 47.5, -71.1, -66.9),
    ("NH", 42.7, 45.3, -72.6, -70.7),
    ("VT", 42.7, 45.0, -73.4, -71.5),
    ("RI", 41.1, 42.0, -71.9, -71.1),
    ("CT", 41.0, 42.0, -73.7, -71.8),
    ("NJ", 38.9, 41.4, -75.6, -73.9),
    ("DE", 38.4, 39.8, -75.8, -75.0),
    ("MD", 37.9, 39.7, -79.5, -75.0),
]


def latlon_to_us_state(lat: float, lon: float) -> Optional[str]:
    if lat is None or lon is None:
        return None
    for st, min_lat, max_lat, min_lon, max_lon in US_STATE_BOUNDS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return st
    return None


def resolve_operator_location_context(
    home_lat: float,
    home_lon: float,
    user_call: str = "",
    grid: str = "",
    resolver: Optional[Any] = None,
) -> dict:
    state = None
    call_district = None

    if home_lat is not None and home_lon is not None:
        state = latlon_to_us_state(home_lat, home_lon)

    if not state and user_call and resolver:
        try:
            user_loc = resolver.lookup_user_callsign(user_call)
            if user_loc and user_loc.state:
                state = user_loc.state
        except Exception:
            pass

    if state and state in US_STATE_CALL_DISTRICT:
        call_district = US_STATE_CALL_DISTRICT[state]

    if not call_district and user_call:
        m = re.search(r"^[AKNW][A-Z]?(\d)", user_call.upper())
        if m:
            call_district = m.group(1)

    is_us = bool(call_district) or (state in US_STATE_CALL_DISTRICT)

    if not is_us and user_call:
        from data_engine import POTA_PREFIX_TO_COUNTRY
        country = None
        clean_call = user_call.upper().strip()
        for i in range(len(clean_call), 0, -1):
            if clean_call[:i] in POTA_PREFIX_TO_COUNTRY:
                country = POTA_PREFIX_TO_COUNTRY[clean_call[:i]]
                break
        
        if country:
            if not state: state = country
            call_district = country
            land_name = country
            op_land_desc = f"{country} / Near {grid[:4] if grid else country}"
        else:
            if not state: state = "DX"
            call_district = "DX"
            land_name = "DX"
            op_land_desc = f"DX / Near {grid[:4] if grid else 'DX'}"
    else:
        if not call_district:
            call_district = "8"
        if not state:
            state = "WV" if call_district == "8" else "US"
        land_name = f"{call_district}-Land" if call_district in "0123456789" else f"{call_district}"
        op_land_desc = f"{land_name} / Near {state}"
    neighbors = US_STATE_NEIGHBORS.get(state, set())

    return {
        "state": state,
        "call_district": call_district,
        "land_name": land_name,
        "op_land_desc": op_land_desc,
        "neighbors": neighbors,
        "grid": grid[:4] if grid else "",
    }


class CallsignResolver:
    """Resolves amateur radio callsigns to state and Maidenhead grid locator."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CallsignResolver, cls).__new__(cls)
                cls._instance._init_cache()
            return cls._instance

    def _init_cache(self):
        self.memory_cache: Dict[str, dict] = {}
        self.cache_dir = os.path.expanduser("~/.cache/pota_comparator")
        self.cache_file = os.path.join(self.cache_dir, "callsigns.json")
        self._load_disk_cache()

    def _load_disk_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
        except Exception as e:
            logger.debug(f"Failed to load callsign cache: {e}")

    def _save_disk_cache(self):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f)
        except Exception as e:
            logger.debug(f"Failed to save callsign cache: {e}")

    @staticmethod
    def is_candidate_local_call(call: str) -> bool:
        if not call:
            return False
        clean = call.strip().upper().split("/")[0].split("-")[0]
        return bool(re.match(r"^[AKNW][A-Z]?\d[A-Z]{1,4}$", clean))

    def resolve(
        self,
        raw_call: str,
        home_lat: Optional[float] = None,
        home_lon: Optional[float] = None,
        op_context: Optional[dict] = None,
    ) -> CallsignLocation:
        if not raw_call:
            return CallsignLocation(callsign="")

        call = raw_call.strip().upper().split("/")[0].split("-")[0]
        if not call:
            return CallsignLocation(callsign=raw_call)

        with self._lock:
            cached = self.memory_cache.get(call)

        if cached is None and self.is_candidate_local_call(call):
            try:
                url = f"https://callook.info/{call}/json"
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "POTA-Comparator/1.0 (Amateur Radio Spot Intelligence)"},
                )
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("status") == "VALID":
                            addr = data.get("address", {})
                            loc = data.get("location", {})
                            state_val = addr.get("state")
                            if not state_val and addr.get("line2"):
                                m = re.search(r",\s*([A-Z]{2})\b", addr.get("line2", ""))
                                if m:
                                    state_val = m.group(1)

                            grid_val = loc.get("gridsquare")
                            lat_val = float(loc.get("latitude")) if loc.get("latitude") else None
                            lon_val = float(loc.get("longitude")) if loc.get("longitude") else None
                            name_val = data.get("name")

                            cached = {
                                "state": state_val,
                                "grid": grid_val,
                                "latitude": lat_val,
                                "longitude": lon_val,
                                "name": name_val,
                            }
                            with self._lock:
                                self.memory_cache[call] = cached
                                self._save_disk_cache()
            except Exception as e:
                logger.debug(f"Callsign lookup failed for {call}: {e}")

        if cached is None:
            state_val = None
            if self.is_candidate_local_call(call):
                m = re.search(r"^[AKNW][A-Z]?(\d)", call)
                call_area = m.group(1) if m else None
                state_val = f"{call_area}-Land" if call_area else None
            else:
                from data_engine import POTA_PREFIX_TO_COUNTRY
                for i in range(len(call), 0, -1):
                    if call[:i] in POTA_PREFIX_TO_COUNTRY:
                        state_val = POTA_PREFIX_TO_COUNTRY[call[:i]]
                        break
                if not state_val:
                    state_val = "DX"
                    
            cached = {"state": state_val, "grid": None, "latitude": None, "longitude": None, "name": None}

        state = cached.get("state")
        grid = cached.get("grid")
        lat = cached.get("latitude")
        lon = cached.get("longitude")
        name = cached.get("name")

        if (lat is None or lon is None) and grid:
            g_lat, g_lon = maidenhead_to_latlon(grid)
            lat, lon = g_lat, g_lon

        dist_mi = None
        if home_lat is not None and home_lon is not None and lat is not None and lon is not None:
            d_km, _ = calculate_distance_and_bearing(home_lat, home_lon, lat, lon)
            dist_mi = d_km * 0.621371

        is_local = False
        op_state = op_context.get("state") if op_context else "WV"
        op_land = op_context.get("call_district") if op_context else "8"

        m_call = re.search(r"^[AKNW][A-Z]?(\d)", call)
        call_district = m_call.group(1) if m_call else None

        if dist_mi is not None:
            if dist_mi <= 200.0:
                is_local = True
        else:
            # Fallback heuristics if distance is unknown
            if state and op_state and state == op_state:
                is_local = True
            elif call_district and op_land and call_district == op_land:
                is_local = True

        return CallsignLocation(
            callsign=call,
            state=state,
            grid=grid,
            latitude=lat,
            longitude=lon,
            name=name,
            distance_miles=dist_mi,
            is_local_area=is_local,
        )

    def lookup_user_callsign(self, raw_call: str) -> Optional[CallsignLocation]:
        if not raw_call:
            return None
        call = raw_call.strip().upper().split("/")[0].split("-")[0]
        if not call:
            return None

        cached = self.memory_cache.get(call)
        if cached and cached.get("grid"):
            return CallsignLocation(
                callsign=call,
                state=cached.get("state"),
                grid=cached.get("grid"),
                latitude=cached.get("latitude"),
                longitude=cached.get("longitude"),
                name=cached.get("name"),
            )

        try:
            url = f"https://callook.info/{call}/json"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "POTA-Hunter-Comparator/1.0 (Amateur Radio Operator Lookup)"},
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("status") == "VALID":
                        addr = data.get("address", {})
                        loc = data.get("location", {})
                        state_val = addr.get("state")
                        if not state_val and addr.get("line2"):
                            m = re.search(r",\s*([A-Z]{2})\b", addr.get("line2", ""))
                            if m:
                                state_val = m.group(1)

                        grid_val = loc.get("gridsquare")
                        lat_val = float(loc.get("latitude")) if loc.get("latitude") else None
                        lon_val = float(loc.get("longitude")) if loc.get("longitude") else None
                        name_val = data.get("name")

                        if not grid_val and lat_val is not None and lon_val is not None:
                            grid_val = latlon_to_maidenhead(lat_val, lon_val)

                        cached = {
                            "state": state_val,
                            "grid": grid_val,
                            "latitude": lat_val,
                            "longitude": lon_val,
                            "name": name_val,
                        }
                        self.memory_cache[call] = cached
                        self._save_disk_cache()
                        return CallsignLocation(
                            callsign=call,
                            state=state_val,
                            grid=grid_val,
                            latitude=lat_val,
                            longitude=lon_val,
                            name=name_val,
                        )
        except Exception as e:
            logger.debug(f"User callsign lookup error for {call}: {e}")

        return None


def maidenhead_to_latlon(grid: str) -> Tuple[Optional[float], Optional[float]]:
    if not grid or not isinstance(grid, str):
        return None, None
    g = grid.strip().upper()
    if len(g) < 4:
        return None, None
    if not (g[0].isalpha() and g[1].isalpha() and g[2].isdigit() and g[3].isdigit()):
        return None, None

    lon = (ord(g[0]) - ord('A')) * 20.0 - 180.0
    lat = (ord(g[1]) - ord('A')) * 10.0 - 90.0
    lon += (ord(g[2]) - ord('0')) * 2.0
    lat += (ord(g[3]) - ord('0')) * 1.0

    if len(g) >= 6 and g[4].isalpha() and g[5].isalpha():
        lon += (ord(g[4]) - ord('A')) * (2.0 / 24.0) + (1.0 / 24.0)
        lat += (ord(g[5]) - ord('A')) * (1.0 / 24.0) + (0.5 / 24.0)
    else:
        lon += 1.0
        lat += 0.5

    return lat, lon


def latlon_to_maidenhead(lat: float, lon: float, precision: int = 6) -> str:
    if lat is None or lon is None:
        return ""
    if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
        return ""
    adj_lon = lon + 180.0
    adj_lat = lat + 90.0

    field_lon = chr(ord('A') + int(adj_lon // 20.0))
    field_lat = chr(ord('A') + int(adj_lat // 10.0))

    square_lon = str(int((adj_lon % 20.0) // 2.0))
    square_lat = str(int((adj_lat % 10.0) // 1.0))

    grid = f"{field_lon}{field_lat}{square_lon}{square_lat}"
    if precision >= 6:
        sub_lon = chr(ord('a') + int(((adj_lon % 2.0) % 2.0) / (2.0 / 24.0)))
        sub_lat = chr(ord('a') + int(((adj_lat % 1.0) % 1.0) / (1.0 / 24.0)))
        grid += f"{sub_lon}{sub_lat}"
    return grid


def calculate_distance_and_bearing(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> Tuple[float, float]:
    R = EARTH_RADIUS_KM
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    distance_km = R * c

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing_rad = math.atan2(y, x)
    bearing_deg = (math.degrees(bearing_rad) + 360.0) % 360.0

    return distance_km, bearing_deg


def calculate_midpoint(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> Tuple[float, float]:
    phi1 = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    phi2 = math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)

    Bx = math.cos(phi2) * math.cos(delta_lon)
    By = math.cos(phi2) * math.sin(delta_lon)

    mid_phi = math.atan2(
        math.sin(phi1) + math.sin(phi2),
        math.sqrt((math.cos(phi1) + Bx) ** 2 + By ** 2),
    )
    mid_lon = lon1_rad + math.atan2(By, math.cos(phi1) + Bx)
    return math.degrees(mid_phi), (math.degrees(mid_lon) + 540.0) % 360.0 - 180.0


def calculate_solar_elevation(lat: float, lon: float, dt_utc: datetime) -> float:
    day_of_year = dt_utc.timetuple().tm_yday
    utc_hours = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0

    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (utc_hours - 12.0) / 24.0)

    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )

    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2.0 * gamma)
        + 0.000907 * math.sin(2.0 * gamma)
        - 0.002697 * math.cos(3.0 * gamma)
        + 0.001480 * math.sin(3.0 * gamma)
    )

    time_offset = eqtime + 4.0 * lon
    tst = utc_hours * 60.0 + time_offset
    ha_deg = (tst / 4.0) - 180.0
    ha_rad = math.radians(ha_deg)

    lat_rad = math.radians(lat)
    sin_elev = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(decl) * math.cos(ha_rad)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.degrees(math.asin(sin_elev))


_SOLAR_CACHE_TIME: Optional[datetime] = None
_SOLAR_CACHE_DATA: Optional[SolarWeather] = None


def fetch_live_solar_weather(timeout: int = 5, force: bool = False, max_age_seconds: float = 900.0) -> SolarWeather:
    global _SOLAR_CACHE_TIME, _SOLAR_CACHE_DATA

    now = datetime.now(timezone.utc)
    if not force and _SOLAR_CACHE_DATA is not None and _SOLAR_CACHE_TIME is not None:
        age = (now - _SOLAR_CACHE_TIME).total_seconds()
        if age < max_age_seconds:
            return _SOLAR_CACHE_DATA

    sfi = 145.0
    k_index = 2.0
    a_index = 8.0
    updated = now.strftime("%H:%M UTC")

    # 1. Fetch SFI
    try:
        req = urllib.request.Request(
            NOAA_10CM_FLUX_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                flux_val = data[0].get("flux")
                if flux_val is not None:
                    sfi = float(flux_val)
    except Exception as e:
        logger.debug("Failed to fetch NOAA SFI: %s", e)

    # 2. Fetch K-index
    try:
        req = urllib.request.Request(
            NOAA_K_INDEX_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 1:
                latest = data[-1]
                if len(latest) >= 2:
                    k_index = float(latest[1])
    except Exception as e:
        logger.debug("Failed to fetch NOAA K-index: %s", e)

    # 3. Fetch A-index
    try:
        req = urllib.request.Request(
            NOAA_A_INDEX_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 1:
                latest = data[-1]
                if len(latest) >= 2:
                    a_index = float(latest[1])
    except Exception as e:
        logger.debug("Failed to fetch NOAA A-index: %s", e)

    # 4. Fetch GOES X-Ray
    xray_flux = 1e-7
    xray_class = "B1.0"
    r_scale = "R0 (Normal)"
    flare_penalty = 0

    try:
        req = urllib.request.Request(
            NOAA_GOES_XRAY_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                entries = [d for d in data if d.get("energy") == "0.1-0.8nm" and d.get("flux") is not None]
                if entries:
                    xray_flux = float(entries[-1].get("flux"))
                    if xray_flux >= 1e-3:
                        xray_class = f"X{xray_flux * 10000:.1f}"
                        r_scale = "R4/R5 Extreme Radio Blackout"
                        flare_penalty = -50
                    elif xray_flux >= 1e-4:
                        xray_class = f"X{xray_flux * 10000:.1f}"
                        r_scale = "R3 Strong Radio Blackout"
                        flare_penalty = -40
                    elif xray_flux >= 5e-5:
                        xray_class = f"M{xray_flux * 100000:.1f}"
                        r_scale = "R2 Moderate Radio Blackout"
                        flare_penalty = -25
                    elif xray_flux >= 1e-5:
                        xray_class = f"M{xray_flux * 100000:.1f}"
                        r_scale = "R1 Minor Radio Blackout"
                        flare_penalty = -15
                    elif xray_flux >= 1e-6:
                        xray_class = f"C{xray_flux * 1000000:.1f}"
                        r_scale = "R0 (Normal)"
                        flare_penalty = 0
                    else:
                        xray_class = f"B{xray_flux * 10000000:.1f}"
                        r_scale = "R0 (Normal)"
                        flare_penalty = 0
    except Exception as e:
        logger.debug("Failed to fetch NOAA GOES X-ray flux: %s", e)

    # 5. Fetch Aurora HPI
    aurora_hpi = 15.0
    try:
        req = urllib.request.Request(
            NOAA_HPI_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lines = resp.read().decode("utf-8").strip().split("\n")
            if len(lines) > 0:
                last_line = lines[-1]
                parts = last_line.split()
                if len(parts) >= 4:
                    aurora_hpi = float(parts[2])
    except Exception as e:
        logger.debug("Failed to fetch NOAA Aurora HPI: %s", e)

    # 6. Fetch Sunspot Number (SSN)
    ssn = int(max(0, (sfi - 63.7) / 0.728))  # Fallback approximation
    try:
        req = urllib.request.Request(
            NOAA_SSN_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lines = resp.read().decode("utf-8").strip().split("\n")
            if len(lines) > 0:
                # The file has a header, followed by lines of data. 
                # The last line should be the most recent day's data.
                last_line = lines[-1]
                parts = last_line.split()
                if len(parts) >= 5 and parts[0].isdigit():
                    ssn = int(parts[4])
    except Exception as e:
        logger.debug("Failed to fetch NOAA SSN: %s", e)

    # 7. Fetch 3-Day K-Index Forecast
    k_forecast = "N/A"
    try:
        req = urllib.request.Request(
            NOAA_3DAY_FORECAST_URL,
            headers={"User-Agent": "POTA-Hunter-Comparator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            forecast_text = resp.read().decode("utf-8")
            match = re.search(r"greatest expected 3 hr Kp for.*?is\s+([0-9.]+)", forecast_text)
            if match:
                k_forecast = match.group(1)
    except Exception as e:
        logger.debug("Failed to fetch NOAA K-index Forecast: %s", e)

    if k_index <= 1:
        cond = "Quiet (Excellent)"
    elif k_index <= 3:
        cond = "Normal (Good)"
    elif k_index == 4:
        cond = "Unsettled"
    elif k_index == 5:
        cond = "Minor Storm (Degraded)"
    else:
        cond = "Major Storm (Severe HF Absorption)"

    if flare_penalty < 0:
        cond = f"{r_scale} ({xray_class} Flare)"

    meteor = get_current_meteor_activity(now)
    res = SolarWeather(
        sfi=sfi,
        ssn=ssn,
        k_index=k_index,
        k_forecast=k_forecast,
        a_index=a_index,
        aurora_hpi=aurora_hpi,
        xray_flux=xray_flux,
        xray_class=xray_class,
        radio_blackout_scale=r_scale,
        flare_penalty=flare_penalty,
        condition=cond,
        updated_at=updated,
        source="NOAA SWPC / GOES",
        meteor_activity=meteor,
    )

    _SOLAR_CACHE_TIME = now
    _SOLAR_CACHE_DATA = res
    return res


def normalize_callsign_base(call: str) -> str:
    """Extracts the base callsign without prefixes or suffixes (e.g. 'W8XYZ/P' -> 'W8XYZ', 'VE3/W8XYZ' -> 'W8XYZ')."""
    if not call:
        return ""
    call = call.strip().upper()
    parts = call.split("/")
    valid_parts = [p for p in parts if p]
    if not valid_parts:
        return ""
    digit_parts = [p for p in valid_parts if any(c.isdigit() for c in p)]
    if digit_parts:
        return max(digit_parts, key=len)
    return max(valid_parts, key=len)


def is_self_spot(spotter_call: str, activator_call: str) -> bool:
    """Checks if a spot is a self-spot posted by the activator themselves."""
    if not spotter_call or not activator_call:
        return False
    base_spotter = normalize_callsign_base(spotter_call)
    base_activator = normalize_callsign_base(activator_call)
    return bool(base_spotter and base_activator and base_spotter == base_activator)


def extract_state_from_location(loc_desc: str) -> str:
    if not loc_desc:
        return ""
    parts = loc_desc.split("-")
    if len(parts) >= 2 and parts[0] == "US":
        return parts[1].upper()
    return loc_desc.upper()


def build_regional_path_matrix(
    spots: List[Any],
    home_lat: float,
    home_lon: float,
    op_call: str,
    user_grid: str,
    resolver: CallsignResolver,
) -> RegionalPathMatrix:
    matrix = RegionalPathMatrix()
    
    op_context = resolve_operator_location_context(
        home_lat=home_lat, home_lon=home_lon, user_call=op_call, grid=user_grid, resolver=resolver
    )
    
    for spot in spots:
        tgt_state = extract_state_from_location(getattr(spot, "location_desc", ""))
        band = getattr(spot, "band", "")
        mode = getattr(spot, "mode", "")
        
        if not tgt_state or not band:
            continue
            
        all_respots = list(getattr(spot, "respots", []) or [])
        comments = getattr(spot, "comments", "")
        if comments:
            has_main = any(str(r.get("comments") or "").strip() == comments for r in all_respots)
            if not has_main:
                all_respots.append({"spotter": getattr(spot, "spotter", ""), "comments": comments})
                
        for r in all_respots:
            spt = r.get("spotter")
            if not spt:
                continue
            if is_self_spot(spt, getattr(spot, "activator", "")):
                continue
            
            loc = resolver.resolve(spt, home_lat=home_lat, home_lon=home_lon, op_context=op_context)
            if loc.is_local_area and loc.distance_miles is not None:
                key = (band.upper(), tgt_state)
                matrix.openings.setdefault(key, []).append((loc.distance_miles, mode.upper(), None, False))
                
    return matrix


def inject_psk_spots(matrix: RegionalPathMatrix, psk_spots: List['DigitalSpot']):
    """
    Ingests live PSKReporter telemetry into the RegionalPathMatrix.
    
    This function tracks the highest SNR achieved per region/band across all 
    network decodes. This allows the scoring engine to implement Mode Penalty Logic, 
    where exceptionally strong FT8 decodes can empirically prove SSB/CW viability,
    while weak decodes only prove digital viability.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for spot in psk_spots:
        if not spot.tx_grid or len(spot.tx_grid) < 2:
            continue
            
        grid2 = spot.tx_grid[:2].upper()
        # Approximate age
        age = (now - spot.time_utc).total_seconds() / 60.0
        if age < 0: age = 0.0
        
        # band string based on freq
        freq = spot.freq_mhz
        if 1.8 <= freq <= 2.0: band = "160m"
        elif 3.5 <= freq <= 4.0: band = "80m"
        elif 5.3 <= freq <= 5.4: band = "60m"
        elif 7.0 <= freq <= 7.3: band = "40m"
        elif 10.1 <= freq <= 10.2: band = "30m"
        elif 14.0 <= freq <= 14.35: band = "20m"
        elif 18.068 <= freq <= 18.168: band = "17m"
        elif 21.0 <= freq <= 21.45: band = "15m"
        elif 24.89 <= freq <= 24.99: band = "12m"
        elif 28.0 <= freq <= 29.7: band = "10m"
        elif 50.0 <= freq <= 54.0: band = "6m"
        else: continue
        
        matrix.openings.setdefault((band, grid2), []).append((age, spot.mode, spot.snr, True))
        
    return matrix


def parse_spot_evidence(
    respots: List[dict],
    home_lat: float,
    home_lon: float,
    activator_call: str = "",
    op_call: str = "",
    user_grid: str = "",
    resolver: Optional[CallsignResolver] = None,
    dt_utc: Optional[datetime] = None,
    psk_spots: Optional[List[Any]] = None,
) -> SpotEvidence:
    if resolver is None:
        resolver = CallsignResolver()
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    op_context = resolve_operator_location_context(
        home_lat=home_lat,
        home_lon=home_lon,
        user_call=op_call,
        grid=user_grid,
        resolver=resolver,
    )

    op_state_code = op_context["state"]
    op_neighbors = op_context["neighbors"]
    op_land = op_context["call_district"]
    op_land_desc = op_context["op_land_desc"]

    if not respots:
        return SpotEvidence(op_land_desc=op_land_desc)

    total_respots = len(respots)
    spotters: List[str] = []
    local_spotters: List[CallsignLocation] = []
    comments: List[str] = []
    local_state_mentions: List[str] = []
    signal_reports: List[str] = []
    max_rbn_snr: Optional[float] = None
    recent_respots_45m = 0

    has_state_mention = False
    has_neighbor_mention = False
    has_positive_sig = False
    has_negative_sig = False

    state_names_map = {
        "WV": ["WV", "WVA", "WEST VIRGINIA", "CHARLESTON"],
        "MA": ["MA", "MASS", "MASSACHUSETTS", "BOSTON"],
        "CA": ["CA", "CALIF", "CALIFORNIA", "LOS ANGELES", "BAY AREA"],
        "TX": ["TX", "TEXAS", "DALLAS", "HOUSTON", "AUSTIN"],
        "FL": ["FL", "FLA", "FLORIDA", "MIAMI", "ORLANDO"],
        "OH": ["OH", "OHIO", "CINCINNATI", "COLUMBUS", "CLEVELAND"],
        "PA": ["PA", "PENN", "PENNSYLVANIA", "PITTSBURGH", "PHILLY"],
        "VA": ["VA", "VIRGINIA", "RICHMOND"],
        "NC": ["NC", "CAROLINA", "CHARLOTTE", "RALEIGH"],
        "NY": ["NY", "NEW YORK", "NYC"],
        "IL": ["IL", "ILLINOIS", "CHICAGO"],
        "MI": ["MI", "MICH", "MICHIGAN", "DETROIT"],
        "GA": ["GA", "GEORGIA", "ATLANTA"],
        "CO": ["CO", "COLORADO", "DENVER"],
        "WA": ["WA", "WASH", "WASHINGTON", "SEATTLE"],
    }
    if op_state_code in ["DX", "Intl", "US"]:
        state_tokens = []
    else:
        state_tokens = state_names_map.get(op_state_code, [op_state_code])
        
    if state_tokens:
        state_pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in state_tokens) + r")\b", re.IGNORECASE)
    else:
        state_pattern = None

    neighbor_tokens = list(op_neighbors)
    neighbor_tokens.append(f"{op_land}-LAND")
    neighbor_tokens.append(f"{op_land}LAND")
    if op_context.get("grid"):
        neighbor_tokens.append(op_context["grid"][:4])

    neighbor_pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in neighbor_tokens if t) + r")\b", re.IGNORECASE
    ) if neighbor_tokens else re.compile(r"a^")

    sig_pattern = re.compile(
        r"\b(5[5-9]9?|4[4-9]9?|20\s*OVER|LOUD|BOOMING|STRONG|SOLID|GREAT\s+SIG|GOOD\s+SIG|\+?\d+\s*dB)\b",
        re.IGNORECASE,
    )
    rbn_pattern = re.compile(r"RBN\s*([+-]?\d+)\s*dB", re.IGNORECASE)
    neg_pattern = re.compile(
        r"\b(QSB|WEAK|NO\s+COPY|FADING|QRM|DEEP\s+QSB|HIGH\s+NOISE|POOR)\b",
        re.IGNORECASE,
    )
    qrt_pattern = re.compile(
        r"\b(QRT|OFF\s+THE\s+AIR|SHUTTING\s+DOWN|PARK\s+CLOSED|CLOSED\s+PARK|SESSION\s+ENDED|DONE\s+ACTIVATING|GOING\s+QRT|73\s+QRT|QRT\s+73|NOW\s+QRT)\b",
        re.IGNORECASE,
    )
    psk_pattern = re.compile(
        r"\b(PSKREPORTER|PSK\s*REPORTER|WSPR|WSPRNET|WSPR\s*DECODE)\b",
        re.IGNORECASE,
    )

    seen_spotters: Set[str] = set()
    is_qrt = False
    has_psk_reporter_decode = False

    for spot in respots:
        spotter = str(spot.get("spotter") or "").strip()
        comment = str(spot.get("comments") or "").strip()
        spot_time_str = spot.get("spotTime") or ""

        # 1. ALWAYS check comments for QRT indicators (self-spot or hunter-spot)
        if comment:
            if qrt_pattern.search(comment.upper()):
                is_qrt = True

        # 2. Check if this is an activator self-spot
        spot_is_self = is_self_spot(spotter, activator_call)
        if spot_is_self:
            # Self-spots must NOT count towards empirical spotter intelligence,
            # local area confirmations, respot frequency boosts, or signal reports.
            if comment and comment not in comments:
                comments.append(comment)
            continue

        # 3. Third-party hunter spot processing
        if spot_time_str:
            try:
                clean_time = spot_time_str.replace("T", " ")
                st = datetime.fromisoformat(clean_time)
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                age_mins = (dt_utc - st).total_seconds() / 60.0
                if age_mins <= 45.0:
                    recent_respots_45m += 1
            except Exception:
                recent_respots_45m += 1
        else:
            recent_respots_45m += 1

        if spotter and spotter.upper() not in seen_spotters:
            seen_spotters.add(spotter.upper())
            spotters.append(spotter)
            loc = resolver.resolve(spotter, home_lat=home_lat, home_lon=home_lon, op_context=op_context)
            
            spot_method = "POTA Respot"
            spot_snr = None
            if comment:
                if psk_pattern.search(comment):
                    spot_method = "PSKReporter (POTA Respot)"
                
                rbn_m = rbn_pattern.search(comment)
                if rbn_m:
                    spot_method = "RBN Node"
                    try:
                        spot_snr = float(rbn_m.group(1))
                    except ValueError:
                        pass
                        
            loc.method = spot_method
            loc.snr = spot_snr

            if loc.is_local_area:
                local_spotters.append(loc)

        if comment:
            if comment not in comments:
                comments.append(comment)
            if psk_pattern.search(comment):
                has_psk_reporter_decode = True

            if state_pattern and state_pattern.search(comment):
                has_state_mention = True
                local_state_mentions.append(f"{op_state_code} ({comment})")
            elif neighbor_pattern.search(comment):
                has_neighbor_mention = True
                m = neighbor_pattern.search(comment)
                if m:
                    local_state_mentions.append(f"{m.group(0).upper()} ({comment})")

            sm = sig_pattern.findall(comment)
            if sm:
                has_positive_sig = True
                signal_reports.extend([s.upper() for s in sm])

            rbn_m = rbn_pattern.search(comment)
            if rbn_m:
                try:
                    snr_val = float(rbn_m.group(1))
                    if max_rbn_snr is None or snr_val > max_rbn_snr:
                        max_rbn_snr = snr_val
                except ValueError:
                    pass

            if neg_pattern.search(comment):
                has_negative_sig = True

    # 4. Integrate raw PSKReporter telemetry for this activator
    if psk_spots and activator_call:
        for spot in psk_spots:
            if spot.tx_call.upper() == activator_call.upper() and spot.rx_call:
                rx_call = spot.rx_call.upper()
                if rx_call not in seen_spotters:
                    seen_spotters.add(rx_call)
                    
                    dist_mi = None
                    is_local = False
                    
                    if getattr(spot, 'rx_grid', None) and home_lat is not None and home_lon is not None:
                        r_lat, r_lon = maidenhead_to_latlon(spot.rx_grid)
                        if r_lat is not None and r_lon is not None:
                            d_km, _ = calculate_distance_and_bearing(home_lat, home_lon, r_lat, r_lon)
                            dist_mi = d_km * 0.621371
                            if dist_mi <= 200.0:
                                is_local = True
                    
                    if is_local:
                        loc = CallsignLocation(
                            callsign=rx_call,
                            grid=spot.rx_grid,
                            distance_miles=dist_mi,
                            is_local_area=True,
                            method="PSKReporter (FT8/FT4)",
                            snr=spot.snr
                        )
                        age_mins = (dt_utc - spot.time_utc).total_seconds() / 60.0 if getattr(spot, 'time_utc', None) else 0.0
                        loc.age_mins = age_mins
                        
                        if age_mins <= 45.0:
                            recent_respots_45m += 1
                            
                        local_spotters.append(loc)
                        has_psk_reporter_decode = True

    boost = 0
    reasons = []

    if local_spotters:
        closest_dist = min([s.distance_miles for s in local_spotters if s.distance_miles is not None] or [999.0])
        closest_call = local_spotters[0].callsign
        land_label = f"{op_land}-Land" if op_land in "0123456789" else f"{op_land}"
        if closest_dist <= 150.0:
            boost += 25
            reasons.append(f"Local spotter {closest_call} ({int(closest_dist)} mi)")
        elif closest_dist <= 300.0:
            boost += 15
            reasons.append(f"Regional spotter {closest_call} ({int(closest_dist)} mi)")
        else:
            boost += 12
            reasons.append(f"{land_label} spotter {closest_call}")

    if has_state_mention:
        if has_positive_sig:
            boost += 25
            reasons.append(f"Direct {op_state_code} 59 report")
        else:
            boost += 15
            reasons.append(f"{op_state_code} mention in spot")
    elif has_neighbor_mention and has_positive_sig:
        boost += 12
        reasons.append("Neighbor state 59 report")

    if max_rbn_snr is not None:
        if max_rbn_snr >= 10.0:
            boost += 10
            reasons.append(f"Strong RBN decode ({int(max_rbn_snr)} dB)")
        elif max_rbn_snr >= 0.0:
            boost += 5
            reasons.append(f"RBN decode ({int(max_rbn_snr)} dB)")

    if has_psk_reporter_decode:
        boost += 15
        reasons.append("Local PSKReporter/WSPR decode")

    if recent_respots_45m >= 4:
        boost += 8
        reasons.append(f"Active activation ({recent_respots_45m} spots in 45m)")
    elif recent_respots_45m >= 2:
        boost += 4
        reasons.append(f"Moderate activation ({recent_respots_45m} spots in 45m)")

    if has_negative_sig and not (has_state_mention or local_spotters):
        boost -= 15
        reasons.append("Reported weak/QSB")

    if is_qrt:
        boost = -100
        summary = "Activator QRT (Off the air)"
    else:
        boost = max(-20, min(35, boost))
        summary = " • ".join(reasons) if reasons else ""

    return SpotEvidence(
        total_respots=total_respots,
        recent_respots_45m=recent_respots_45m,
        spotters=spotters,
        local_spotters=local_spotters,
        comments=comments,
        local_state_mentions=local_state_mentions,
        signal_reports=signal_reports,
        max_rbn_snr_db=max_rbn_snr,
        empirical_boost_pct=boost,
        evidence_summary=summary,
        op_land_desc=op_land_desc,
        is_qrt=is_qrt,
        has_psk_reporter_decode=has_psk_reporter_decode,
    )


def resolve_antenna_preset(antenna_type: str) -> Dict[str, Any]:
    if not antenna_type:
        return ANTENNA_PRESETS["EFHW"]
    clean = antenna_type.strip()
    if clean.upper() in ANTENNA_PRESETS:
        return ANTENNA_PRESETS[clean.upper()]
    norm_key = clean.upper().replace("-", "_").replace(" ", "_").replace("/", "_")
    if norm_key in ANTENNA_PRESETS:
        return ANTENNA_PRESETS[norm_key]
    for k, v in ANTENNA_PRESETS.items():
        if clean.lower() in v["name"].lower() or v["name"].lower() in clean.lower():
            return v
    return ANTENNA_PRESETS["EFHW"]


def calculate_antenna_elevation_gain(
    antenna_type: str,
    takeoff_angle_deg: float,
    freq_mhz: float,
    dist_km: float = 500.0,
) -> Tuple[float, str]:
    """
    Synthesizes dynamic angle-of-arrival antenna gain (in dBi) from elevation
    radiation patterns as a function of the ray path's takeoff launch angle (Delta),
    operating frequency (MHz), and antenna electromagnetic design.

    Returns (gain_dbi, pattern_diagnostic).
    """
    ant_conf = resolve_antenna_preset(antenna_type)
    ant_key = ant_conf.get("key", "EFHW").upper()
    elev = max(0.5, min(89.5, float(takeoff_angle_deg)))

    # 1. VHF / UHF Modes (>= 140 MHz)
    if freq_mhz >= 140.0:
        if ant_key == "BEAM":
            gain = 9.5
            desc = "Yagi Beam (+9.5 dBi forward directive gain)"
        elif ant_key == "VHF_COLLINEAR":
            gain = 7.0
            desc = "Collinear Base (+7.0 dBi low-horizon gain)"
        elif ant_key == "VERTICAL":
            gain = 2.2  # 0 dBd = ~2.2 dBi 1/4-wave groundplane
            desc = "1/4λ GP (+2.2 dBi omni vertical)"
        elif ant_key in ("DIPOLE", "EFHW"):
            gain = 1.5
            desc = "Dipole/EFHW (+1.5 dBi horizontal)"
        elif ant_key == "RANDOM_WIRE":
            gain = -3.5
            desc = "Random Wire (-3.5 dBi matching loss)"
        elif ant_key == "MAG_LOOP":
            gain = -5.0
            desc = "Mag Loop (-5.0 dBi loss)"
        elif ant_key == "RUBBER_DUCK":
            gain = -6.5
            desc = "HT Rubber Duck (-6.5 dBi loss)"
        else:
            gain = 0.0
            desc = "Standard Antenna (0.0 dBi)"
        return round(gain, 1), desc

    # 2. HF & 6m Bands (1.8 - 54 MHz)
    if ant_key == "BEAM":
        # 3-Element Yagi / Hexbeam (35-50ft):
        # High forward gain peaking at 12-18 deg (~+9.5 to +10.5 dBi), strong mid-angle support
        if elev <= 5.0:
            gain = 5.5 + (elev / 5.0) * 3.5  # +5.5 to +9.0 dBi
        elif elev <= 22.0:
            lobe_factor = 1.0 - ((elev - 15.0) / 12.0) ** 2
            gain = 8.5 + 2.0 * max(0.0, lobe_factor)  # up to +10.5 dBi peak
        elif elev <= 45.0:
            gain = 8.5 - ((elev - 22.0) / 23.0) * 4.0  # +8.5 down to +4.5 dBi
        else:
            gain = max(1.5, 4.5 - ((elev - 45.0) / 45.0) * 3.0)  # +4.5 down to +1.5 dBi NVIS
        desc = f"Beam/Yagi ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "DIPOLE":
        # Resonant Horizontal 1/2-wave Dipole / Inverted-V at ~35ft:
        # High angle NVIS / regional specialist (+6.0 to +7.0 dBi at 35°-65°).
        # Low angle rolloff due to ground reflection cancellation (+0.5 to +2.5 dBi at <10°).
        if elev <= 10.0:
            gain = 0.5 + (elev / 10.0) * 3.0  # +0.5 to +3.5 dBi
        elif elev <= 35.0:
            gain = 3.5 + ((elev - 10.0) / 25.0) * 2.8  # +3.5 to +6.3 dBi
        elif elev <= 65.0:
            gain = 6.3 + math.sin(math.radians((elev - 35.0) * (180.0 / 30.0))) * 0.7  # up to +7.0 dBi peak NVIS
        else:
            gain = max(4.0, 6.3 - ((elev - 65.0) / 25.0) * 2.0)  # +6.3 down to +4.3 dBi
        desc = f"Dipole ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "VERTICAL":
        # 1/4-wave Ground Plane / Vertical:
        # Low-angle DX specialist: peak at 8°-18° (+4.5 to +5.0 dBi).
        # Deep overhead null at high angles (>50° drops down to -6.0 to -12.0 dBi).
        if elev <= 5.0:
            gain = 2.0 + (elev / 5.0) * 2.2  # +2.0 to +4.2 dBi
        elif elev <= 20.0:
            gain = 4.2 + (1.0 - abs(elev - 12.0) / 8.0) * 0.8  # +4.2 to +5.0 dBi peak
        elif elev <= 40.0:
            gain = 4.2 - ((elev - 20.0) / 20.0) * 4.0  # +4.2 down to +0.2 dBi
        elif elev <= 60.0:
            gain = 0.2 - ((elev - 40.0) / 20.0) * 6.0  # +0.2 down to -5.8 dBi
        else:
            gain = max(-12.0, -5.8 - ((elev - 60.0) / 30.0) * 6.0)  # -5.8 down to -11.8 dBi deep null
        desc = f"Vertical ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "EFHW":
        # End-Fed Half-Wave with 49:1 autotransformer:
        # Resonant multi-band wire, broad inverted-V pattern minus ~1.5 dB core loss
        if elev <= 10.0:
            raw_gain = 1.0 + (elev / 10.0) * 2.5
        elif elev <= 50.0:
            raw_gain = 3.5 + math.sin(math.radians((elev - 10.0) * (180.0 / 40.0))) * 1.5  # up to +5.0 dBi
        else:
            raw_gain = max(2.5, 4.5 - ((elev - 50.0) / 40.0) * 1.8)
        gain = raw_gain - 1.5  # 1.5 dB transformer core insertion loss
        desc = f"EFHW ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "RANDOM_WIRE":
        # Non-resonant Random Wire with 9:1 UnUn & Tuner:
        # Sump transformer loss, non-resonant SWR mismatch, and ground return losses
        if elev <= 15.0:
            raw_gain = 0.5 + (elev / 15.0) * 1.5
        elif elev <= 55.0:
            raw_gain = 2.0 + math.sin(math.radians((elev - 15.0) * (180.0 / 40.0))) * 1.0
        else:
            raw_gain = 1.5
        gain = raw_gain - 4.5  # Net -1.5 to -4.0 dBi
        desc = f"Random Wire ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "MAG_LOOP":
        # Small Transmitting Magnetic Loop:
        # High Q, low radiation resistance on lower HF bands (-4 to -8 dBi), improving on higher bands
        band_eff_loss = 6.5 if freq_mhz <= 7.5 else (4.0 if freq_mhz <= 15.0 else 2.0)
        raw_gain = 2.0 * math.cos(math.radians(max(0.0, elev - 20.0)))
        gain = raw_gain - band_eff_loss
        desc = f"Mag Loop ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "RUBBER_DUCK":
        # Handheld HT whip on HF: extreme loss
        gain = -22.0 if freq_mhz <= 30.0 else -12.0
        desc = f"Rubber Duck ({gain:+.1f} dBi @ {elev:.1f}°)"

    elif ant_key == "VHF_COLLINEAR":
        # VHF Collinear used out-of-band on HF
        gain = -3.0
        desc = f"VHF Collinear on HF ({gain:+.1f} dBi)"

    else:
        gain = 0.0
        desc = f"Standard ({gain:+.1f} dBi @ {elev:.1f}°)"

    return round(gain, 1), desc


# ---------------------------------------------------------------------------
# Multi-Layer Ionospheric Profiler & Ray-Tracing Solver
# ---------------------------------------------------------------------------

@dataclass
class IonosphericProfile:
    """Multi-layer ionospheric parameters at midpoint reflection coordinate."""
    foE: float         # E-layer critical frequency (MHz)
    foF1: float        # F1-layer critical frequency (MHz)
    foF2: float        # F2-layer critical frequency (MHz)
    hmE: float         # E-layer height (km)
    hmF2: float        # F2-layer peak height (km)
    ymF2: float        # F2-layer semi-thickness (km)
    h_prime_F2: float  # Oblique virtual reflection height for F2 (km)
    M3000: float       # M(3000)F2 factor
    daylight_path: float


def compute_ionospheric_profile(
    mid_lat: float,
    mid_lon: float,
    home_elev: float,
    mid_elev: float,
    target_elev: float,
    sfi: float,
    k_index: float,
    a_index: float,
    dt_utc: datetime,
    meteor_activity: Optional[MeteorActivity] = None,
    aurora_hpi: float = 15.0,
) -> IonosphericProfile:
    """
    Computes multi-layer electron density profile (E, F1, F2).
    Includes sub-storm negative phase ion depletion and diurnal solar zenith scaling.
    """
    day_of_year = dt_utc.timetuple().tm_yday
    season_factor = 1.0 + 0.15 * math.cos(2.0 * math.pi * (day_of_year - 300) / 365.0)

    # 1. Daylight path fraction (weighted home, mid, target)
    day_home = max(0.0, math.sin(math.radians(max(0.0, home_elev))))
    day_mid = max(0.0, math.sin(math.radians(max(0.0, mid_elev))))
    day_target = max(0.0, math.sin(math.radians(max(0.0, target_elev))))
    daylight_path = (day_home + 2.0 * day_mid + day_target) / 4.0

    # 2. E-Layer Chapman formulation (foE & hmE)
    if mid_elev > 0.0:
        zenith_sin = math.sin(math.radians(mid_elev))
        foE = 0.9 * ((180.0 + 1.44 * sfi) * max(0.01, zenith_sin)) ** 0.25
    else:
        foE = 0.45  # Nighttime residual E-layer

    if meteor_activity and meteor_activity.zhr >= 15:
        # Boost foE proportionally to meteor activity to model Sporadic-E enhancement
        zhr_boost = 1.0 + (meteor_activity.zhr / 100.0) * 0.20
        foE = foE * zhr_boost

    hmE = 110.0

    # 3. F1-Layer (daytime only)
    foF1 = 1.4 * foE if mid_elev > 10.0 else 0.0

    # 4. F2-Layer Base & Solar Zenith Coupling
    sin_mid_elev = math.sin(math.radians(max(0.0, mid_elev)))
    foF2_base = 4.2 + 0.045 * (sfi - 65.0)
    
    # At night, the ionosphere decays, but during high solar activity the retention is much stronger.
    # Solar min retention ~65%. Solar max retention ~85-90%.
    night_retention = 0.65 + 0.002 * max(0.0, sfi - 65.0)
    night_retention = min(0.95, night_retention)
    
    day_factor = night_retention + (1.0 - night_retention) * (sin_mid_elev ** 0.5)
    foF2_zenith = foF2_base * day_factor * season_factor

    # 5. Geomagnetic Sub-Storm & Negative Phase Ion Depletion
    # In sub-storms (even K=2-3), F2 layer recombination rates increase, depleting foF2
    k_deplet = 1.0 - 0.08 * max(0.0, k_index - 1.5) - 0.005 * max(0.0, a_index - 15.0)
    
    # HPI Depletion (Immediate, real-time reflection of storm intensity)
    hpi_deplet = 0.0
    if aurora_hpi >= 35.0:
        hpi_deplet = (aurora_hpi - 30.0) * 0.008

    if abs(mid_lat) >= 45.0:
        k_deplet -= 0.06 * max(0.0, k_index - 1.0)
        hpi_deplet *= 1.5
        
    total_deplet = k_deplet - hpi_deplet
    # Drop floor to 0.15 for severe storms (enabling complete band washout)
    foF2 = max(1.8, foF2_zenith * max(0.15, min(1.0, total_deplet)))

    # 6. Parabolic Layer Height & Semi-Thickness
    M3000 = 3.0 * (1.0 + 0.12 * math.cos(2.0 * math.pi * (day_of_year - 300) / 365.0))
    hmF2 = max(220.0, min(420.0, 1490.0 / M3000 - 176.0 + (45.0 if mid_elev <= 0 else 0.0)))
    ymF2 = 0.35 * hmF2
    h_prime_F2 = max(200.0, hmF2 - 0.5 * ymF2)

    return IonosphericProfile(
        foE=round(foE, 2),
        foF1=round(foF1, 2),
        foF2=round(foF2, 2),
        hmE=hmE,
        hmF2=round(hmF2, 1),
        ymF2=round(ymF2, 1),
        h_prime_F2=round(h_prime_F2, 1),
        M3000=round(M3000, 2),
        daylight_path=daylight_path,
    )


@dataclass
class RayHopCandidate:
    mode_name: str
    hop_count: int
    hop_dist_km: float
    takeoff_angle_deg: float
    incidence_angle_deg: float
    oblique_muf_mhz: float
    is_penetrated: bool  # True if freq > oblique MUF (Skip zone cutoff)
    is_screened_by_e: bool  # True if E-layer cutoff shields F2 ray
    slant_dist_km: float
    virtual_height_km: float


def trace_candidate_ray_modes(
    dist_km: float, freq_mhz: float, profile: IonosphericProfile
) -> List[RayHopCandidate]:
    """
    Evaluates candidate HF ray path modes (1E, 2E, 1F2, 2F2, 3F2, 4F2)
    calculating exact take-off launch angle, ionospheric incidence angle, oblique MUF,
    and skip-zone penetration cutoff.
    """
    candidates: List[RayHopCandidate] = []
    modes_to_test: List[Tuple[str, int, float, float]] = []

    # Select candidate modes based on Great Circle distance
    if dist_km <= 2000.0:
        modes_to_test.append(("1E", 1, profile.hmE, profile.foE))
        modes_to_test.append(("1F2", 1, profile.h_prime_F2, profile.foF2))
    elif dist_km <= 4000.0:
        modes_to_test.append(("1F2", 1, profile.h_prime_F2, profile.foF2))
        modes_to_test.append(("2E", 2, profile.hmE, profile.foE))
        modes_to_test.append(("2F2", 2, profile.h_prime_F2, profile.foF2))
    elif dist_km <= 8000.0:
        modes_to_test.append(("2F2", 2, profile.h_prime_F2, profile.foF2))
        modes_to_test.append(("3F2", 3, profile.h_prime_F2, profile.foF2))
    else:
        modes_to_test.append(("3F2", 3, profile.h_prime_F2, profile.foF2))
        modes_to_test.append(("4F2", 4, profile.h_prime_F2, profile.foF2))

    R = EARTH_RADIUS_KM
    for name, hops, h_prime, fo_layer in modes_to_test:
        d_hop = dist_km / float(hops)
        theta_hop = d_hop / (2.0 * R)  # Angular hop radius in radians

        # 1. Takeoff elevation angle Δ
        num = math.cos(theta_hop) - (R / (R + h_prime))
        den = math.sin(theta_hop)
        if den == 0:
            continue
        tan_delta = num / den
        delta_rad = math.atan(tan_delta)
        delta_deg = math.degrees(delta_rad)

        if delta_deg < 0.1:
            # Below horizon cutoff
            continue

        # 2. Ionospheric incidence angle φ_inc
        cos_delta = math.cos(max(0.0, delta_rad))
        sin_phi = (R / (R + h_prime)) * cos_delta
        sin_phi = max(0.0, min(0.9999, sin_phi))
        cos_phi = math.sqrt(1.0 - sin_phi ** 2)
        phi_inc_deg = math.degrees(math.asin(sin_phi))

        # 3. Oblique MUF secant law: f_muf = fo / cos(phi_inc)
        oblique_muf = fo_layer / max(0.08, cos_phi)

        # High SFI daytime boost on upper HF
        if profile.daylight_path > 0.3 and name.endswith("F2") and profile.foF2 >= 7.0:
            oblique_muf = max(oblique_muf, oblique_muf * 1.08)

        is_penetrated = freq_mhz > (oblique_muf * 1.05)

        # 4. E-Layer Screening check on F2 modes in daytime
        is_screened = False
        if name.endswith("F2") and profile.foE >= 1.8:
            sin_phi_e = (R / (R + profile.hmE)) * cos_delta
            if sin_phi_e < 1.0:
                cos_phi_e = math.sqrt(1.0 - sin_phi_e ** 2)
                f_e_screen = profile.foE / max(0.1, cos_phi_e)
                if freq_mhz < f_e_screen:
                    is_screened = True

        # 5. Slant path distance
        hop_slant = 2.0 * math.sqrt(R ** 2 + (R + h_prime) ** 2 - 2.0 * R * (R + h_prime) * math.cos(theta_hop))
        total_slant = hop_slant * float(hops)

        candidates.append(
            RayHopCandidate(
                mode_name=name,
                hop_count=hops,
                hop_dist_km=d_hop,
                takeoff_angle_deg=round(delta_deg, 1),
                incidence_angle_deg=round(phi_inc_deg, 1),
                oblique_muf_mhz=round(oblique_muf, 1),
                is_penetrated=is_penetrated,
                is_screened_by_e=is_screened,
                slant_dist_km=round(total_slant, 1),
                virtual_height_km=h_prime,
            )
        )

    return candidates


def calculate_qso_probability(
    home_lat: float,
    home_lon: float,
    target_lat: Optional[float],
    target_lon: Optional[float],
    target_grid: Optional[str],
    freq_khz: float,
    band: str,
    mode: str,
    solar_weather: Optional[SolarWeather] = None,
    dt_utc: Optional[datetime] = None,
    spot_evidence: Optional[SpotEvidence] = None,
    tx_power_watts: float = DEFAULT_TX_POWER_WATTS,
    antenna_type: str = DEFAULT_ANTENNA_TYPE,
    is_same_park: bool = False,
    lightning_summary: Optional[Any] = None,
    regional_matrix: Optional[RegionalPathMatrix] = None,
    target_state: str = "",
) -> PropagationResult:
    """
    Calculates Circuit Reliability, SNR, multi-hop ray tracing,
    skip-zone cutoff, ITU-R P.372 atmospheric noise with lightning QRN, and spot evidence.
    """
    if solar_weather is None:
        solar_weather = SolarWeather()
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    # Station Link Budget
    ant_conf = resolve_antenna_preset(antenna_type)
    actual_ant_key = ant_conf.get("key", "EFHW")
    tx_watts = max(0.5, float(tx_power_watts or DEFAULT_TX_POWER_WATTS))
    db_power = 10.0 * math.log10(tx_watts / 100.0)

    # 0. Immediate QRT check: If activator is off the air, probability is always 0
    if spot_evidence and spot_evidence.is_qrt:
        d_km, d_brg = (0.0, 0.0)
        if target_lat is not None and target_lon is not None:
            d_km, d_brg = calculate_distance_and_bearing(home_lat, home_lon, target_lat, target_lon)
        return PropagationResult(
            probability_pct=0,
            distance_km=d_km,
            distance_miles=d_km * 0.621371,
            bearing_deg=d_brg,
            path_type="Activator QRT / Station Off Air",
            path_summary="Activator QRT (Off the air)",
            muf_est_mhz=0.0,
            is_grayline=False,
            solar_info=solar_weather,
            spot_evidence=spot_evidence,
            tx_power_watts=tx_watts,
            antenna_type=actual_ant_key,
            antenna_gain_dbi=0.0,
            station_offset_db=round(db_power, 1),
            predicted_snr_db=-99.0,
            circuit_reliability_pct=0,
            ray_mode="QRT",
            lightning_summary=lightning_summary,
        )

    # Resolve target lat/lon
    t_lat = target_lat
    t_lon = target_lon
    if (t_lat is None or t_lon is None) and target_grid:
        g_lat, g_lon = maidenhead_to_latlon(target_grid)
        if g_lat is not None and g_lon is not None:
            t_lat, t_lon = g_lat, g_lon

    if t_lat is None or t_lon is None:
        fallback_prob = 50
        if spot_evidence and spot_evidence.empirical_boost_pct != 0:
            fallback_prob = max(10, min(95, fallback_prob + spot_evidence.empirical_boost_pct))
        return PropagationResult(
            probability_pct=fallback_prob,
            distance_km=0.0,
            distance_miles=0.0,
            bearing_deg=0.0,
            path_type="Unknown",
            path_summary="Target coordinates unavailable",
            muf_est_mhz=0.0,
            is_grayline=False,
            solar_info=solar_weather,
            spot_evidence=spot_evidence,
            tx_power_watts=tx_watts,
            antenna_type=actual_ant_key,
            antenna_gain_dbi=0.0,
            station_offset_db=round(db_power, 1),
            predicted_snr_db=None,
            circuit_reliability_pct=fallback_prob,
            ray_mode="N/A",
            lightning_summary=lightning_summary,
        )

    # 1. Great Circle Geometry
    dist_km, bearing = calculate_distance_and_bearing(home_lat, home_lon, t_lat, t_lon)
    dist_miles = dist_km * 0.621371
    freq_mhz = freq_khz / 1000.0 if freq_khz > 0 else 14.0
    clean_mode = (mode or "SSB").upper()

    # 1a. Co-located / Same Park P2P Groundwave Check
    if is_same_park or dist_km <= 1.5:
        return PropagationResult(
            probability_pct=99,
            distance_km=dist_km,
            distance_miles=dist_miles,
            bearing_deg=bearing,
            path_type="Same Park / Direct Groundwave",
            path_summary="Co-located / Same Park P2P (Guaranteed Direct Signal)",
            muf_est_mhz=freq_mhz,
            is_grayline=False,
            solar_info=solar_weather,
            spot_evidence=spot_evidence,
            tx_power_watts=tx_watts,
            antenna_type=actual_ant_key,
            antenna_gain_dbi=0.0,
            station_offset_db=round(db_power, 1),
            predicted_snr_db=45.0,
            circuit_reliability_pct=99,
            ray_mode="Direct Groundwave",
            takeoff_angle_deg=0.0,
            hop_count=1,
            path_loss_db=45.0,
            noise_floor_dbw=-135.0,
            qrn_surge_db=0.0,
            lightning_summary=lightning_summary,
            profile=IonosphericProfile(0.5, 0.0, 5.0, 110.0, 300.0, 100.0, 250.0, 3.0, 0.0),
            ray_candidate=RayHopCandidate("Direct Groundwave", 1, dist_km, 0.0, 90.0, freq_mhz, False, False, dist_km, 1.0)
        )

    # 1b. Check RegionalPathMatrix for fuzzy logic multi-mode openings
    regional_boost = 0
    regional_summary = ""
    if regional_matrix:
        openings = []
        if target_state:
            openings.extend(regional_matrix.openings.get((band.upper(), target_state), []))
        if target_grid and len(target_grid) >= 2:
            openings.extend(regional_matrix.openings.get((band.upper(), target_grid[:2].upper()), []))
            
        if openings:
            # For POTA spots, distance is in index 0. For PSK spots, age is in index 0. 
            # Both signify "closeness" of the evidence. We just consider all found openings.
            best_dist = min([o[0] for o in openings])
            best_modes = [o[1] for o in openings if o[0] == best_dist]
            best_snrs = [o[2] for o in openings if o[2] is not None]
            
            # Determine if the opening was created by a weak signal mode
            weak_modes = {"FT8", "FT4", "JS8", "WSPR", "CW", "JT65"}
            opened_by_weak = all(m in weak_modes for m in best_modes)
            target_is_voice = clean_mode in {"SSB", "FM", "AM"}
            
            target_is_cw = clean_mode == "CW"

            # Mode Penalty Logic
            if (target_is_voice or target_is_cw) and opened_by_weak:
                if best_snrs:
                    max_snr = max(best_snrs)
                    if target_is_voice:
                        if max_snr >= 0:
                            regional_boost = 15
                            regional_summary = f"{band} path confirmed open by exceptionally strong FT8 ({max_snr}dB SNR)"
                        elif max_snr >= -8:
                            regional_boost = 5
                            regional_summary = f"{band} path confirmed open by moderate FT8 ({max_snr}dB SNR - marginal for Voice)"
                        else:
                            regional_boost = 0
                            regional_summary = ""
                    elif target_is_cw:
                        if max_snr >= -12:
                            regional_boost = 15
                            regional_summary = f"{band} path confirmed open by strong FT8 ({max_snr}dB SNR - good for CW)"
                        elif max_snr >= -18:
                            regional_boost = 5
                            regional_summary = f"{band} path confirmed open by weak FT8 ({max_snr}dB SNR - marginal for CW)"
                        else:
                            regional_boost = 0
                            regional_summary = ""
                else:
                    # Weak signal evidence without SNR shouldn't optimistically boost Voice/CW
                    regional_boost = 0
                    regional_summary = ""
            else:
                regional_boost = 15
                loc_type = target_state if target_state else (target_grid[:2] if target_grid else "region")
                regional_summary = f"{band} path to {loc_type} confirmed open by local spotters"
                    
    # Inject regional boost into evidence
    if spot_evidence and regional_boost > 0:
        spot_evidence.regional_boost = regional_boost
        spot_evidence.regional_summary = regional_summary

    mid_lat, mid_lon = calculate_midpoint(home_lat, home_lon, t_lat, t_lon)

    # 2. Solar elevation calculations
    home_elev = calculate_solar_elevation(home_lat, home_lon, dt_utc)
    target_elev = calculate_solar_elevation(t_lat, t_lon, dt_utc)
    mid_elev = calculate_solar_elevation(mid_lat, mid_lon, dt_utc)

    # Grayline condition
    is_home_twilight = -8.0 <= home_elev <= 6.0
    is_target_twilight = -8.0 <= target_elev <= 6.0
    is_mid_twilight = -8.0 <= mid_elev <= 6.0
    is_grayline = (is_home_twilight and is_target_twilight) or is_mid_twilight

    # -------------------------------------------------------------
    # 3. VHF / UHF Line-of-Sight & Horizon Physics (144 / 432 MHz)
    # -------------------------------------------------------------
    if freq_mhz >= 140.0:
        db_ant, _ = calculate_antenna_elevation_gain(
            actual_ant_key,
            takeoff_angle_deg=0.5,
            freq_mhz=freq_mhz,
            dist_km=dist_km,
        )
        station_offset_db = round(db_power + db_ant, 1)

        if dist_km <= 35.0:
            prob = 92
            summary = "Local Line-of-Sight (Strong Groundwave)"
        elif dist_km <= 80.0:
            prob = int(85.0 - (dist_km - 35.0) * 0.9)
            summary = "Regional Line-of-Sight / Tropo Fringe"
        elif dist_km <= 150.0:
            prob = int(35.0 - (dist_km - 80.0) * 0.4)
            summary = "Extended Tropospheric / Mountain Scatter"
        else:
            prob = 0
            summary = f"Beyond VHF Horizon ({int(dist_miles)} mi > 100 mi limit)"

        if clean_mode in ("FT8", "FT4", "DIGITAL") and prob > 0:
            prob = min(98, prob + 12)
        elif clean_mode == "CW" and prob > 0:
            prob = min(95, prob + 6)
        elif clean_mode == "FM" and dist_km > 100.0:
            prob = max(0, prob - 15)

        if spot_evidence and spot_evidence.local_spotters and prob > 0:
            prob = min(98, prob + 10)

        if prob > 0:
            vhf_boost = max(-15.0, min(15.0, station_offset_db * 0.85))
            prob = max(1, min(99, int(round(prob + vhf_boost))))

        path_desc = "VHF/UHF Line-of-Sight" if prob > 0 else "Beyond Horizon"
        return PropagationResult(
            probability_pct=max(0, min(100, prob)),
            distance_km=dist_km,
            distance_miles=dist_miles,
            bearing_deg=bearing,
            path_type=path_desc,
            path_summary=summary,
            muf_est_mhz=freq_mhz,
            is_grayline=False,
            solar_info=solar_weather,
            spot_evidence=spot_evidence,
            tx_power_watts=tx_watts,
            antenna_type=actual_ant_key,
            antenna_gain_dbi=db_ant,
            station_offset_db=station_offset_db,
            predicted_snr_db=15.0 if prob > 50 else -5.0,
            circuit_reliability_pct=prob,
            ray_mode="Tropospheric LOS",
            takeoff_angle_deg=0.5,
            hop_count=1,
            path_loss_db=110.0 + dist_km * 0.5,
            noise_floor_dbw=-144.0,
            qrn_surge_db=0.0,
            lightning_summary=lightning_summary,
            profile=IonosphericProfile(0.5, 0.0, 5.0, 110.0, 300.0, 100.0, 250.0, 3.0, 0.0),
            ray_candidate=RayHopCandidate("Tropospheric LOS", 1, dist_km, 0.5, 85.0, freq_mhz, prob == 0, False, dist_km, 3.0)
        )

    # -------------------------------------------------------------
    # 4. 6m Band (50 MHz - "The Magic Band")
    # -------------------------------------------------------------
    if 48.0 <= freq_mhz <= 54.0:
        db_ant, _ = calculate_antenna_elevation_gain(
            actual_ant_key,
            takeoff_angle_deg=2.5,
            freq_mhz=freq_mhz,
            dist_km=dist_km,
        )
        station_offset_db = round(db_power + db_ant, 1)

        month = dt_utc.month
        is_summer_sporadic_e = (month in (5, 6, 7, 8)) and (mid_elev > -6.0)
        is_meteor_scatter = solar_weather.meteor_activity and solar_weather.meteor_activity.zhr >= 15

        if dist_km <= 90.0:
            prob = 85
            summary = "6m Groundwave / Local Line-of-Sight"
            r_mode = "6m Groundwave"
        elif is_summer_sporadic_e and 600.0 <= dist_km <= 2200.0:
            prob = 65
            summary = "6m Summer Sporadic-E Skip Opening"
            r_mode = "1Es Sporadic-E"
        elif is_meteor_scatter and 800.0 <= dist_km <= 2200.0:
            prob = 60 + min(30, int(solar_weather.meteor_activity.zhr / 5.0))
            summary = f"6m Meteor Scatter ({solar_weather.meteor_activity.active_shower})"
            r_mode = "Meteor Scatter"
        elif dist_km <= 250.0:
            prob = 30
            summary = "6m Tropospheric Scatter / Marginal"
            r_mode = "Tropo Scatter"
        else:
            prob = 5
            summary = "6m Band Closed (No Es Opening Detected)"
            r_mode = "Closed / Penetration"

        if spot_evidence:
            total_empirical_boost = spot_evidence.empirical_boost_pct + spot_evidence.regional_boost
            prob = max(1, min(99, prob + total_empirical_boost))
            # If we have a regional summary but no specific evidence summary, use it
            if not spot_evidence.evidence_summary and spot_evidence.regional_summary:
                spot_evidence.evidence_summary = spot_evidence.regional_summary
            elif spot_evidence.evidence_summary and spot_evidence.regional_summary:
                spot_evidence.evidence_summary += f" • {spot_evidence.regional_summary}"

        if prob > 0:
            sixm_boost = max(-15.0, min(15.0, station_offset_db * 0.75))
            prob = max(1, min(99, int(round(prob + sixm_boost))))

        return PropagationResult(
            probability_pct=prob,
            distance_km=dist_km,
            distance_miles=dist_miles,
            bearing_deg=bearing,
            path_type="6m Magic Band (Es/Tropo)",
            path_summary=summary,
            muf_est_mhz=50.0 if is_summer_sporadic_e else 28.0,
            is_grayline=False,
            solar_info=solar_weather,
            spot_evidence=spot_evidence,
            tx_power_watts=tx_watts,
            antenna_type=actual_ant_key,
            antenna_gain_dbi=db_ant,
            station_offset_db=station_offset_db,
            predicted_snr_db=5.0 if prob > 50 else -15.0,
            circuit_reliability_pct=prob,
            ray_mode=r_mode,
            takeoff_angle_deg=2.5,
            hop_count=1,
            path_loss_db=130.0,
            noise_floor_dbw=-142.0,
            qrn_surge_db=0.0,
            lightning_summary=lightning_summary,
            profile=IonosphericProfile(5.0 if is_summer_sporadic_e else 0.5, 0.0, 5.0, 110.0, 300.0, 100.0, 250.0, 3.0, max(0.0, mid_elev / 90.0)),
            ray_candidate=RayHopCandidate(
                r_mode, 1, dist_km, 
                0.5 if "Scatter" in r_mode or "Groundwave" in r_mode else 2.5,
                80.0, 50.0 if is_summer_sporadic_e else 28.0, 
                prob <= 5 and r_mode == "Closed / Penetration", False, dist_km, 
                5.0 if "Scatter" in r_mode or "Groundwave" in r_mode else (90.0 if r_mode == "Meteor Scatter" else 110.0)
            )
        )

    # -------------------------------------------------------------
    # 5. HF Propagation Calculations (160m to 10m / 1.8 - 30 MHz)
    # -------------------------------------------------------------
    sfi = solar_weather.sfi
    k_idx = solar_weather.k_index
    a_idx = solar_weather.a_index

    # A. Multi-layer Ionospheric Profile (E, F1, F2)
    profile = compute_ionospheric_profile(
        mid_lat=mid_lat,
        mid_lon=mid_lon,
        home_elev=home_elev,
        mid_elev=mid_elev,
        target_elev=target_elev,
        sfi=sfi,
        k_index=k_idx,
        a_index=a_idx,
        dt_utc=dt_utc,
        meteor_activity=solar_weather.meteor_activity,
        aurora_hpi=solar_weather.aurora_hpi,
    )

    # B. Multi-Hop Ray Tracing & Mode Selection
    candidates = trace_candidate_ray_modes(dist_km=dist_km, freq_mhz=freq_mhz, profile=profile)

    # Find the primary open / viable ray mode with lowest path attenuation
    primary_mode: Optional[RayHopCandidate] = None
    viable_candidates = [c for c in candidates if not c.is_penetrated and not c.is_screened_by_e]

    if viable_candidates:
        # Prefer F2 modes for long-distance skywave paths, then lowest hop count, then takeoff angle
        viable_candidates.sort(
            key=lambda c: (
                0 if "F2" in c.mode_name else 1,
                c.hop_count,
                c.takeoff_angle_deg,
            )
        )
        primary_mode = viable_candidates[0]
    elif candidates:
        # Fall back to candidate for telemetry
        primary_mode = candidates[0]
    else:
        # Default single hop F2 proxy
        primary_mode = RayHopCandidate(
            mode_name="1F2",
            hop_count=1,
            hop_dist_km=dist_km,
            takeoff_angle_deg=5.0,
            incidence_angle_deg=45.0,
            oblique_muf_mhz=profile.foF2 * 2.2,
            is_penetrated=freq_mhz > profile.foF2 * 2.2,
            is_screened_by_e=False,
            slant_dist_km=dist_km + 100.0,
            virtual_height_km=profile.h_prime_F2,
        )

    muf_est = primary_mode.oblique_muf_mhz
    is_penetrated = primary_mode.is_penetrated
    is_screened = primary_mode.is_screened_by_e

    # C. Dynamic Antenna Elevation Radiation Pattern Calculation
    # Evaluates antenna gain at the exact takeoff angle solved by the ray tracer
    db_ant, ant_desc = calculate_antenna_elevation_gain(
        antenna_type=actual_ant_key,
        takeoff_angle_deg=primary_mode.takeoff_angle_deg,
        freq_mhz=freq_mhz,
        dist_km=dist_km,
    )
    station_offset_db = round(db_power + db_ant, 1)

    # D. Transmission Loss Formulation
    # 1. Free space path loss L_bf
    d_slant = max(100.0, primary_mode.slant_dist_km)
    l_bf = 32.45 + 20.0 * math.log10(freq_mhz) + 20.0 * math.log10(d_slant)

    # 2. Ionospheric absorption loss L_a (ITU-R P.533 non-deviative D-layer + deviative F2)
    # Evaluates secant obliquity factor sec(phi_D) through 75 km D-layer
    daylight_path = profile.daylight_path
    if daylight_path > 0.01:
        r_d = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + 75.0)
        sin_phi_d = r_d * math.cos(math.radians(max(0.5, primary_mode.takeoff_angle_deg)))
        sec_phi_d = 1.0 / math.sqrt(max(0.01, 1.0 - sin_phi_d ** 2))

        # Vertical 1-way daytime absorption at 10 MHz scaled by gyrofrequency ~1.4 MHz
        a_d_vert = 4.5 * (daylight_path ** 0.70) * ((10.0 / (freq_mhz + 1.4)) ** 1.75)
        # 2 transits per hop (up and down through D-layer)
        l_a = 2.0 * primary_mode.hop_count * a_d_vert * sec_phi_d
        l_a = min(35.0, max(0.5, l_a))
    else:
        l_a = 0.5  # Nighttime residual absorption

    # 2b. Auroral Absorption (AA) / Polar Cap Absorption
    # Severe particle precipitation in the auroral oval causes intense D-layer absorption at high latitudes
    max_lat = max(abs(home_lat), abs(target_lat), abs(mid_lat))
    if max_lat >= 50.0 and solar_weather.aurora_hpi > 30.0:
        # Scale absorption by how far north the path goes and how intense the HPI is
        # Auroral absorption is roughly inversely proportional to frequency squared (1/f^2)
        lat_factor = min(1.0, (max_lat - 45.0) / 25.0)  # Max out at 70 deg lat
        hpi_factor = min(2.0, (solar_weather.aurora_hpi - 30.0) / 45.0)
        # Base absorption scaler = 50 dB
        aa_loss = 50.0 * lat_factor * hpi_factor * ((10.0 / freq_mhz) ** 2.0)
        l_a += min(60.0, aa_loss)

    # 2c. Real-time NOAA SWPC D-RAP Absorption
    drap_loss = get_drap_attenuation(mid_lat, mid_lon, freq_mhz)
    l_a += (drap_loss * primary_mode.hop_count)

    # 3. Ground reflection loss L_g for multi-hop paths (e.g. 2F2 = 1 ground bounce ~ 3.0 dB)
    l_g = (primary_mode.hop_count - 1) * 3.0

    # 4. Ionospheric reflection & scatter loss L_i (deviative absorption / polarization coupling)
    # The ionosphere is not a perfect mirror; each bounce scatters energy.
    l_i = primary_mode.hop_count * 4.0

    # Total Path Loss in dB
    total_path_loss_db = round(l_bf + l_a + l_g + l_i, 1)

    # E. ITU-R P.372 Noise Calculation + Real-Time Lightning QRN
    # 1. Man-made noise figure (quiet rural / residential amateur baseline with modern DSP)
    f_man = max(8.0, 48.0 - 27.7 * math.log10(freq_mhz))
    # 2. Galactic noise figure (penetrating above critical plasma frequency)
    f_gal = max(2.0, 48.0 - 23.0 * math.log10(freq_mhz))
    # 3. Atmospheric baseline noise figure (ITU-R P.372 diurnal atmospheric noise)
    # At night, lack of D-layer absorption allows distant global thunderstorm sferics to elevate LF/MF/low-HF noise.
    f_atm_day = max(4.0, 52.0 - 32.0 * math.log10(freq_mhz))
    f_atm_night = max(4.0, 68.5 - 37.5 * math.log10(freq_mhz))
    sun_factor = max(0.0, min(1.0, daylight_path))
    f_atm_base = (sun_factor * f_atm_day) + ((1.0 - sun_factor) * f_atm_night)

    # 4. Add dynamic lightning QRN surge if available
    qrn_surge_db = 0.0
    if lightning_summary is not None and hasattr(lightning_summary, "get_qrn_surge_db"):
        try:
            qrn_surge_db = lightning_summary.get_qrn_surge_db(freq_mhz)
        except Exception:
            qrn_surge_db = 0.0

    f_atm_total = f_atm_base + qrn_surge_db

    # Total Noise Figure F_a
    f_a = 10.0 * math.log10(10.0 ** (f_man / 10.0) + 10.0 ** (f_gal / 10.0) + 10.0 ** (f_atm_total / 10.0))

    # Receiver Bandwidth (Hz) per mode
    if clean_mode in ("FT8", "FT4", "JS8", "DIGITAL"):
        bw_hz = 50.0
        snr_req_db = -21.0
    elif clean_mode == "CW":
        bw_hz = 500.0
        snr_req_db = -10.0
    elif clean_mode in ("SSB", "PHONE"):
        bw_hz = 2400.0
        snr_req_db = 4.0
    elif clean_mode == "AM":
        bw_hz = 6000.0
        snr_req_db = 16.0
    else:
        bw_hz = 2400.0
        snr_req_db = 8.0

    # Total Receiver Noise Power in Bandwidth (dBW)
    noise_power_dbw = -204.0 + 10.0 * math.log10(bw_hz) + f_a

    # F. Transmitter Power & Received Signal Power (dBW)
    tx_power_dbw = 10.0 * math.log10(tx_watts)  # dBW (100W = -10 dBW)
    pota_activator_offset_db = -2.0  # Activator portable field deployment / compromised ground offset
    flare_offset_db = float(solar_weather.flare_penalty) * 0.4 if daylight_path > 0.05 else 0.0

    # Received signal power in dBW
    rx_signal_dbw = (
        tx_power_dbw
        + db_ant
        - total_path_loss_db
        + pota_activator_offset_db
        + flare_offset_db
    )

    # Signal-to-Noise Ratio (dB)
    snr_db = round(rx_signal_dbw - noise_power_dbw, 1)

    # G. Circuit Reliability (REL) via Log-Normal Error Distribution
    # Standard deviation sigma combines path fading variance (~6.0 dB)
    sigma_fading = 6.5
    
    # Auroral Flutter Fading
    max_lat = max(abs(home_lat), abs(target_lat), abs(mid_lat))
    if solar_weather.k_index >= 4.0 or solar_weather.aurora_hpi >= 40.0:
        if max_lat >= 45.0:
            # Rapid multipath fading from auroral boundary irregularities
            sigma_fading += min(6.0, (solar_weather.aurora_hpi - 30.0) / 10.0 + max(0.0, solar_weather.k_index - 3.0))
    snr_margin = snr_db - snr_req_db
    rel_normalized = snr_margin / (math.sqrt(2.0) * sigma_fading)
    raw_rel_pct = 0.5 * (1.0 + math.erf(rel_normalized)) * 100.0

    # H. Skip-Zone, E-Screening, & Storm Penalties
    if is_penetrated and regional_boost == 0:
        # Operating frequency exceeds Oblique MUF -> ray penetrates layer into space!
        # Skip-zone dead-zone cutoff. Bypassed if regional matrix confirms path is open via anomaly!
        raw_rel_pct = max(0.0, min(12.0, raw_rel_pct * 0.10))
    elif is_screened:
        raw_rel_pct = max(5.0, raw_rel_pct - 25.0)

    # Grayline enhancement
    if is_grayline and freq_mhz <= 22.0:
        gray_boost = 18.0 if (is_home_twilight and is_target_twilight) else 12.0
        raw_rel_pct = min(98.0, raw_rel_pct + gray_boost)

    # Major Geomagnetic storm penalty (K-index and planetary A-index)
    storm_sub = 0.0
    if k_idx >= 4:
        storm_sub += (k_idx - 3) * 8.0
    if a_idx >= 20.0:
        storm_sub += (a_idx - 15.0) * 0.4
    if storm_sub > 0:
        if abs(mid_lat) >= 48.0:
            storm_sub *= 1.4
        raw_rel_pct = max(5.0, raw_rel_pct - storm_sub)

    # Apply Regional Matrix Boost to the raw score EVEN IF there is no Spot Evidence (e.g. for the Heatmap!)
    if regional_boost > 0:
        raw_rel_pct = max(1.0, min(99.0, raw_rel_pct + regional_boost))

    # I. Spot Evidence Fusion
    if spot_evidence:
        # Note: regional_boost is already applied to raw_rel_pct above
        total_empirical_boost = spot_evidence.empirical_boost_pct
        
        # Severe local QRN suppression: If the hunter's local noise floor is roaring due to 
        # thunderstorms, the fact that a remote spotting network can hear the activator
        # doesn't help the hunter hear them. We suppress the network boost proportionally.
        if qrn_surge_db > 15.0:
            suppression_factor = max(0.0, 1.0 - ((qrn_surge_db - 15.0) / 35.0)) # Fades to 0 at 50dB surge (S9+20)
            total_empirical_boost *= suppression_factor
            
        # Skip-Zone Suppression: If the physics model mathematically proves the target is 
        # inside the user's skip-zone, we usually suppress global spots.
        # HOWEVER, if a local spotter actually heard them, it proves there is a localized 
        # propagation anomaly overriding the theoretical skip-zone! We MUST trust local human ears.
        if is_penetrated and regional_boost == 0:
            has_local_evidence = len(spot_evidence.local_spotters) > 0
            if not has_local_evidence:
                total_empirical_boost *= 0.10
            
        raw_rel_pct = max(1.0, min(99.0, raw_rel_pct + float(total_empirical_boost)))
        if not spot_evidence.evidence_summary and spot_evidence.regional_summary:
            spot_evidence.evidence_summary = spot_evidence.regional_summary
        elif spot_evidence.evidence_summary and spot_evidence.regional_summary:
            spot_evidence.evidence_summary += f" • {spot_evidence.regional_summary}"

    final_prob = int(round(raw_rel_pct))
    final_prob = max(0, min(100, final_prob))

    # QRT override
    if spot_evidence and spot_evidence.is_qrt:
        final_prob = 0
        path_type = "Activator QRT / Station Off Air"
        summary_quality = "Activator QRT (Off the air)"
    else:
        # Path classification
        if is_grayline:
            path_type = "Grayline Twilight Path"
        elif freq_mhz >= 28.0 and primary_mode.mode_name == "1E" and solar_weather.meteor_activity and solar_weather.meteor_activity.zhr >= 15:
            path_type = f"10m Meteor Scatter ({solar_weather.meteor_activity.active_shower})"
        elif mid_elev > 0:
            path_type = "Daylight Ionospheric Skywave"
        else:
            path_type = "Nighttime Dark Path (Low Absorption)"

        # Build concise diagnostic explanation
        if spot_evidence and spot_evidence.evidence_summary:
            summary_quality = spot_evidence.evidence_summary
        elif is_penetrated:
            summary_quality = f"Closed (Skip Zone / Penetration: Freq {freq_mhz:.1f} MHz > MUF {muf_est:.1f} MHz)"
        elif final_prob >= 75:
            summary_quality = f"Optimal {primary_mode.mode_name} Skywave (SNR {snr_db:+.0f} dB)"
        elif final_prob >= 50:
            summary_quality = f"Good {primary_mode.mode_name} Propagation (SNR {snr_db:+.0f} dB)"
        elif final_prob >= 25:
            summary_quality = f"Fair / Marginal Path (SNR {snr_db:+.0f} dB)"
        else:
            if l_a > 20.0:
                summary_quality = f"Heavy D-Layer Absorption (-{int(l_a)} dB loss)"
            else:
                summary_quality = f"Weak Signal / High Path Loss (SNR {snr_db:+.0f} dB)"

        if qrn_surge_db >= 6.0:
            summary_quality += f" • ⚡ QRN +{qrn_surge_db:.0f}dB"
        if solar_weather.flare_penalty < 0 and daylight_path > 0.05:
            summary_quality += f" • {solar_weather.radio_blackout_scale} ({solar_weather.xray_class})"

    return PropagationResult(
        probability_pct=final_prob,
        distance_km=dist_km,
        distance_miles=dist_miles,
        bearing_deg=bearing,
        path_type=path_type,
        path_summary=summary_quality,
        muf_est_mhz=round(muf_est, 1),
        is_grayline=is_grayline,
        solar_info=solar_weather,
        spot_evidence=spot_evidence,
        tx_power_watts=tx_watts,
        antenna_type=actual_ant_key,
        antenna_gain_dbi=db_ant,
        station_offset_db=station_offset_db,
        predicted_snr_db=snr_db,
        circuit_reliability_pct=int(round(raw_rel_pct)),
        ray_mode="QRT" if (spot_evidence and spot_evidence.is_qrt) else (primary_mode.mode_name if not is_penetrated else "Skip Zone Cutoff"),
        takeoff_angle_deg=primary_mode.takeoff_angle_deg,
        hop_count=primary_mode.hop_count,
        path_loss_db=total_path_loss_db,
        noise_floor_dbw=round(noise_power_dbw, 1),
        qrn_surge_db=round(qrn_surge_db, 1),
        drap_loss_db=round(drap_loss, 1),
        lightning_summary=lightning_summary,
        profile=profile,
        ray_candidate=primary_mode,
    )


# -------------------------------------------------------------
# Band Noise Floor Matrix Calculator (ITU-R P.372 & Live Lightning)
# -------------------------------------------------------------
AMATEUR_BANDS_NOISE_PROFILES = [
    ("160m", 1.840),
    ("80m", 3.550),
    ("60m", 5.350),
    ("40m", 7.150),
    ("30m", 10.125),
    ("20m", 14.150),
    ("17m", 18.110),
    ("15m", 21.250),
    ("12m", 24.940),
    ("10m", 28.500),
    ("6m", 50.150),
]


def compute_band_noise_matrix(
    home_lat: float,
    home_lon: float,
    solar_weather: Optional[SolarWeather] = None,
    lightning_summary: Optional[Any] = None,
    dt_utc: Optional[datetime] = None,
    bandwidth_hz: float = 2400.0,
) -> List[BandNoiseBreakdown]:
    """
    Computes a comprehensive noise breakdown across all amateur HF/VHF bands:
    - Diurnal ITU-R P.372 atmospheric baseline (day vs night global lightning ducting)
    - Real-time regional lightning surge (from Blitzortung + NWS warnings)
    - Galactic cosmic noise floor
    - Man-made environmental noise floor
    - Total combined receiver noise figure (Fa), noise power (dBm), and S-meter readings.
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    if solar_weather is None:
        solar_weather = SolarWeather()

    # Calculate solar elevation at operator's QTH for diurnal day/night transition
    sol_elev = calculate_solar_elevation(home_lat, home_lon, dt_utc)
    if sol_elev >= 0.0:
        daylight_factor = 1.0
    elif sol_elev <= -12.0:
        daylight_factor = 0.0
    else:
        # Astronomical to nautical/civil twilight interpolation
        daylight_factor = (sol_elev + 12.0) / 12.0

    results: List[BandNoiseBreakdown] = []

    for band_name, freq_mhz in AMATEUR_BANDS_NOISE_PROFILES:
        # 1. Atmospheric baseline (ITU-R P.372 diurnal curves)
        f_atm_day = max(6.0, 56.0 - 32.0 * math.log10(freq_mhz))
        f_atm_night = max(6.0, 72.5 - 37.5 * math.log10(freq_mhz))
        f_atm_base = (daylight_factor * f_atm_day) + ((1.0 - daylight_factor) * f_atm_night)

        # 2. Live regional lightning QRN surge (dB)
        qrn_surge = 0.0
        if lightning_summary is not None and hasattr(lightning_summary, "get_qrn_surge_db"):
            try:
                qrn_surge = lightning_summary.get_qrn_surge_db(freq_mhz)
            except Exception:
                qrn_surge = 0.0

        f_atm_total = f_atm_base + qrn_surge

        # 3. Galactic / Cosmic noise figure (dB)
        f_gal = max(4.0, 52.0 - 23.0 * math.log10(freq_mhz))

        # 4. Man-made baseline noise figure (quiet rural / residential amateur baseline)
        f_man = max(10.0, 52.0 - 27.7 * math.log10(freq_mhz))

        # 5. Total Noise Figure F_a (dB)
        f_a_total = 10.0 * math.log10(
            10.0 ** (f_man / 10.0) + 10.0 ** (f_gal / 10.0) + 10.0 ** (f_atm_total / 10.0)
        )

        # 6. Receiver Noise Power in Bandwidth (dBm)
        # Thermal noise floor kTB = -174 dBm/Hz + 10*log10(BW) + Fa
        # Subtracting 3.0 dB for assumed typical feedline/system loss
        noise_power_dbm = -174.0 + 10.0 * math.log10(bandwidth_hz) + f_a_total - 3.0

        # 7. S-Unit calculation (IARU HF standard: S9 = -73 dBm, S0 = -127 dBm, 6 dB/S-unit)
        s_val = (noise_power_dbm - (-127.0)) / 6.0
        if s_val < 0.2:
            s_label = "S0 (Quiet)"
        elif s_val <= 9.0:
            s_label = f"S{int(round(s_val))}"
        else:
            db_over = noise_power_dbm - (-73.0)
            s_label = f"S9+{int(round(db_over))}dB"

        # 8. Dominant noise source
        p_atm = 10.0 ** (f_atm_total / 10.0)
        p_gal = 10.0 ** (f_gal / 10.0)
        p_man = 10.0 ** (f_man / 10.0)
        if p_atm >= p_gal and p_atm >= p_man:
            dominant = "Atmosphere (QRN)"
        elif p_gal >= p_man:
            dominant = "Space / Cosmic"
        else:
            dominant = "Man-Made (QRM)"

        is_elevated = (qrn_surge >= 3.0) or (s_val >= 4.0)

        results.append(
            BandNoiseBreakdown(
                band=band_name,
                freq_mhz=freq_mhz,
                f_atm_base_db=round(f_atm_base, 1),
                qrn_surge_db=round(qrn_surge, 1),
                f_atm_total_db=round(f_atm_total, 1),
                f_gal_db=round(f_gal, 1),
                f_man_db=round(f_man, 1),
                f_a_total_db=round(f_a_total, 1),
                noise_power_dbm=round(noise_power_dbm, 1),
                s_units_val=round(s_val, 1),
                s_units_label=s_label,
                dominant_source=dominant,
                is_elevated_qrn=is_elevated,
            )
        )

    return results
