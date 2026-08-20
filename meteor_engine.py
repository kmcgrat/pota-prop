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

SHOWER_DATABASE = {
    "Quadrantids": {
        "origin": "Asteroid 2003 EH1",
        "history": "Discovered in the 1820s, it's one of the few major showers originating from an asteroid rather than a comet.",
        "peak_date": "January 3"
    },
    "Lyrids": {
        "origin": "Comet C/1861 G1 (Thatcher)",
        "history": "One of the oldest known meteor showers, with records of observations by Chinese astronomers dating back to 687 BC.",
        "peak_date": "April 22"
    },
    "Eta Aquariids": {
        "origin": "Halley's Comet",
        "history": "Created by debris left behind by the famous Halley's Comet. It's particularly strong in the Southern Hemisphere.",
        "peak_date": "May 6"
    },
    "Southern Delta Aquariids": {
        "origin": "Comet 96P/Machholz",
        "history": "Discovered by Donald Machholz in 1986. Produces a steady stream of meteors lacking persistent trains.",
        "peak_date": "July 30"
    },
    "Perseids": {
        "origin": "Comet 109P/Swift-Tuttle",
        "history": "Often the most spectacular shower of the year, famous for its bright meteors and long persistent trains. Known as the 'Tears of St. Lawrence'.",
        "peak_date": "August 12"
    },
    "Orionids": {
        "origin": "Halley's Comet",
        "history": "The second shower created by Halley's Comet. Known for extremely fast meteors that occasionally leave glowing trains.",
        "peak_date": "October 21"
    },
    "Leonids": {
        "origin": "Comet 55P/Tempel-Tuttle",
        "history": "Famous for producing historic 'meteor storms' every 33 years, some featuring tens of thousands of meteors per hour.",
        "peak_date": "November 17"
    },
    "Geminids": {
        "origin": "Asteroid 3200 Phaethon",
        "history": "Often the strongest and most reliable shower of the year. Uniquely originates from a 'rock comet' (asteroid) instead of a regular icy comet.",
        "peak_date": "December 14"
    },
    "Ursids": {
        "origin": "Comet 8P/Tuttle",
        "history": "A relatively minor shower that peaks right around the winter solstice, discovered in the early 20th century.",
        "peak_date": "December 22"
    }
}


@dataclass
class MeteorActivity:
    zhr: int
    activity_level: str  # Low, Moderate, High, Storm
    active_shower: str
    days_to_peak: int = 0
    next_shower_name: str = ""
    next_shower_days: int = 0

    def format_tooltip_html(self) -> str:
        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 13px; min-width: 300px; max-width: 350px;'>")
        lines.append("<div style='margin-bottom: 8px;'><b style='font-size: 15px; color: #bc8cff;'>Meteor Activity Analysis</b></div>")
        
        lines.append(f"<div style='margin-bottom: 4px;'><b>Active Shower:</b> <span style='color: #79c0ff;'>{self.active_shower}</span></div>")
        lines.append(f"<div style='margin-bottom: 4px;'><b>Zenithal Hourly Rate (ZHR):</b> <span style='color: #f1e05a;'>{self.zhr} meteors/hr</span></div>")
        lines.append(f"<div style='margin-bottom: 12px;'><b>Activity Level:</b> {self.activity_level}</div>")
        
        if self.active_shower != "Sporadic Background" and self.active_shower in SHOWER_DATABASE:
            info = SHOWER_DATABASE[self.active_shower]
            lines.append("<hr style='border: 1px solid #30363d; margin: 8px 0;'>")
            lines.append(f"<div style='margin-bottom: 4px; color: #58a6ff;'><b>{self.active_shower} Facts:</b></div>")
            lines.append(f"<div style='margin-bottom: 4px;'><b>Origin:</b> {info['origin']}</div>")
            lines.append(f"<div style='margin-bottom: 4px;'><b>Annual Peak:</b> {info['peak_date']}</div>")
            
            if self.days_to_peak > 0:
                peak_str = f"<span style='color:#7ee787;'>Approaching peak in {self.days_to_peak} day(s).</span>"
            elif self.days_to_peak < 0:
                peak_str = f"<span style='color:#ffa657;'>Fading. Passed peak {-self.days_to_peak} day(s) ago.</span>"
            else:
                peak_str = f"<span style='color:#ff7b72;'><b>PEAKING TODAY!</b></span>"
                
            lines.append(f"<div style='margin-bottom: 6px;'><b>Status:</b> {peak_str}</div>")
            lines.append(f"<div style='margin-bottom: 8px; font-size: 11px; color: #8b949e; line-height: 1.3;'><i>{info['history']}</i></div>")
        elif self.active_shower == "Sporadic Background" and self.next_shower_name:
            lines.append("<hr style='border: 1px solid #30363d; margin: 8px 0;'>")
            lines.append(f"<div style='margin-bottom: 8px; color: #8b949e;'><i>Next major shower: <b>{self.next_shower_name}</b> peaks in {self.next_shower_days} days.</i></div>")
        
        lines.append("<hr style='border: 1px solid #30363d; margin: 8px 0;'>")
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
    active_days_to_peak = 0
    
    current_day_of_year = dt_utc.timetuple().tm_yday
    
    next_shower_name = ""
    next_shower_days = 999
    
    for shower in MAJOR_SHOWERS:
        # Create a dummy datetime for the peak in the current year to get day of year
        try:
            peak_dt = datetime(dt_utc.year, shower.peak_month, shower.peak_day, tzinfo=timezone.utc)
            peak_day_of_year = peak_dt.timetuple().tm_yday
        except ValueError:
            continue # Leap year issues with Feb 29 etc.
            
        # Calculate distance in days, accounting for year wrap-around
        days_to_peak_val = peak_day_of_year - current_day_of_year
        if days_to_peak_val < -180:
            days_to_peak_val += 365
        elif days_to_peak_val > 180:
            days_to_peak_val -= 365
            
        diff_days = abs(days_to_peak_val)
        
        # Track the next upcoming shower
        if 0 < days_to_peak_val < next_shower_days:
            next_shower_days = days_to_peak_val
            next_shower_name = shower.name
        
        # If within the active duration, calculate the ZHR contribution using a Gaussian curve
        if diff_days <= shower.duration_days:
            # sigma is roughly duration / 4 so that 2 standard deviations covers the duration
            sigma = max(1.0, shower.duration_days / 4.0)
            contribution = shower.peak_zhr * math.exp(-0.5 * (diff_days / sigma) ** 2)
            
            if contribution > current_zhr - 5: # Subtract sporadic background
                current_zhr = int(5 + contribution)
                active_shower_name = shower.name
                active_days_to_peak = days_to_peak_val

    if current_zhr >= 100:
        level = "Storm"
    elif current_zhr >= 30:
        level = "High"
    elif current_zhr >= 15:
        level = "Moderate"
    else:
        level = "Low"

    return MeteorActivity(zhr=current_zhr, activity_level=level, active_shower=active_shower_name, days_to_peak=active_days_to_peak, next_shower_name=next_shower_name, next_shower_days=next_shower_days)


def get_upcoming_meteor_showers(limit: int = 3, dt_utc: datetime = None) -> list:
    """
    Returns the next upcoming meteor showers sorted by days until peak.
    Each item contains: name, peak_date, peak_zhr, days_until_peak, and origin.
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    current_day_of_year = dt_utc.timetuple().tm_yday
    upcoming = []

    for shower in MAJOR_SHOWERS:
        try:
            peak_dt = datetime(dt_utc.year, shower.peak_month, shower.peak_day, tzinfo=timezone.utc)
            peak_day_of_year = peak_dt.timetuple().tm_yday
        except ValueError:
            continue

        days_to_peak_val = peak_day_of_year - current_day_of_year
        if days_to_peak_val <= 0:
            days_to_peak_val += 365

        info = SHOWER_DATABASE.get(shower.name, {})
        upcoming.append({
            "name": shower.name,
            "peak_date": info.get("peak_date", f"{shower.peak_month}/{shower.peak_day}"),
            "peak_zhr": shower.peak_zhr,
            "days_until_peak": days_to_peak_val,
            "origin": info.get("origin", "Cometary debris"),
        })

    upcoming.sort(key=lambda s: s["days_until_peak"])
    return upcoming[:limit]
