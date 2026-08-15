"""
meteor_engine.py - Meteor Activity & ZHR Prediction Engine
Part of POTA Hunter Application

Calculates current Zenithal Hourly Rate (ZHR) based on a calendar of major meteor showers.
Provides data to enhance foE and enable Meteor Scatter path types in the propagation engine.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import math

logger = logging.getLogger(__name__)


@dataclass
class MeteorShower:
    name: str
    peak_month: int
    peak_day: int
    peak_zhr: int
    duration_days: float  # How many days the shower is active around the peak


# Major annual meteor showers
MAJOR_SHOWERS = [
    MeteorShower("Quadrantids", 1, 3, 110, 5.0),
    MeteorShower("Lyrids", 4, 22, 18, 10.0),
    MeteorShower("Eta Aquariids", 5, 6, 50, 20.0),
    MeteorShower("Southern Delta Aquariids", 7, 30, 25, 20.0),
    MeteorShower("Perseids", 8, 12, 100, 20.0),
    MeteorShower("Orionids", 10, 21, 20, 15.0),
    MeteorShower("Leonids", 11, 17, 15, 10.0),
    MeteorShower("Geminids", 12, 14, 150, 15.0),
    MeteorShower("Ursids", 12, 22, 10, 5.0),
]


@dataclass
class MeteorActivity:
    zhr: int
    activity_level: str  # Low, Moderate, High, Storm
    active_shower: str

    def format_tooltip_html(self) -> str:
        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 13px; min-width: 300px;'>")
        lines.append("<div style='margin-bottom: 8px;'><b style='font-size: 15px; color: #bc8cff;'>Meteor Activity Analysis</b></div>")
        
        lines.append(f"<div style='margin-bottom: 4px;'><b>Active Shower:</b> <span style='color: #79c0ff;'>{self.active_shower}</span></div>")
        lines.append(f"<div style='margin-bottom: 4px;'><b>Zenithal Hourly Rate (ZHR):</b> <span style='color: #f1e05a;'>{self.zhr} meteors/hr</span></div>")
        lines.append(f"<div style='margin-bottom: 12px;'><b>Activity Level:</b> {self.activity_level}</div>")
        
        lines.append("<div style='margin-bottom: 4px; color: #8b949e; font-size: 11px;'><i>Propagation Impact:</i></div>")
        if self.zhr >= 15:
            lines.append("<div style='margin-bottom: 4px;'>High meteor rates create ionized trails in the E-layer. This enables momentary <b>Meteor Scatter</b> propagation on 10m and 6m bands, often allowing QSOs over 500-1500 miles even when the F2 layer is closed.</div>")
        else:
            lines.append("<div style='margin-bottom: 4px;'>Current meteor rates are low (mostly sporadic background dust). Meteor scatter propagation is unlikely unless you encounter a random large fireball.</div>")
            
        lines.append("</div>")
        return "".join(lines)


def get_current_meteor_activity(dt_utc: datetime = None) -> MeteorActivity:
    """
    Calculates the current Zenithal Hourly Rate (ZHR) based on the annual calendar.
    Uses a Gaussian distribution around the peak date for each major shower.
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
        
    current_zhr = 5  # Sporadic background meteor rate is roughly 5-10
    active_shower_name = "Sporadic Background"
    
    current_day_of_year = dt_utc.timetuple().tm_yday
    
    for shower in MAJOR_SHOWERS:
        # Create a dummy datetime for the peak in the current year to get day of year
        try:
            peak_dt = datetime(dt_utc.year, shower.peak_month, shower.peak_day, tzinfo=timezone.utc)
            peak_day_of_year = peak_dt.timetuple().tm_yday
        except ValueError:
            continue # Leap year issues with Feb 29 etc.
            
        # Calculate distance in days, accounting for year wrap-around
        diff_days = min(
            abs(current_day_of_year - peak_day_of_year),
            abs(current_day_of_year - (peak_day_of_year + 365)),
            abs((current_day_of_year + 365) - peak_day_of_year)
        )
        
        # If within the active duration, calculate the ZHR contribution using a Gaussian curve
        if diff_days <= shower.duration_days:
            # sigma is roughly duration / 4 so that 2 standard deviations covers the duration
            sigma = max(1.0, shower.duration_days / 4.0)
            contribution = shower.peak_zhr * math.exp(-0.5 * (diff_days / sigma) ** 2)
            
            if contribution > current_zhr - 5: # Subtract sporadic background
                current_zhr = int(5 + contribution)
                active_shower_name = shower.name

    # Determine activity level
    level = "Low"
    if current_zhr > 100:
        level = "Storm"
    elif current_zhr >= 40:
        level = "High"
    elif current_zhr >= 15:
        level = "Moderate"

    return MeteorActivity(
        zhr=current_zhr,
        activity_level=level,
        active_shower=active_shower_name
    )

