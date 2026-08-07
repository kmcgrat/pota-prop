"""
weather_engine.py - Open-Meteo Local Weather Monitoring & 12-Hour Hourly Forecast Engine
Part of POTA Hunter Application

Fetches current weather and 12-hour hourly forecast data from Open-Meteo (free API),
provides in-memory TTL caching, and generates dark-mode GitHub-styled HTML tooltips.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from typing import List, Optional, Tuple
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

# WMO Weather Interpretation Codes (WW) mapping to (Description, Emoji/Icon, Short Label)
WMO_WEATHER_CODES = {
    0: ("Clear Sky", "☀️", "Clear"),
    1: ("Mainly Clear", "🌤️", "Mainly Clear"),
    2: ("Partly Cloudy", "⛅", "Part Cloud"),
    3: ("Overcast", "☁️", "Overcast"),
    45: ("Foggy", "🌫️", "Fog"),
    48: ("Depositing Rime Fog", "🌫️", "Rime Fog"),
    51: ("Light Drizzle", "🌧️", "Lt Drizzle"),
    53: ("Moderate Drizzle", "🌧️", "Drizzle"),
    55: ("Dense Drizzle", "🌧️", "Hvy Drizzle"),
    56: ("Light Freezing Drizzle", "🌧️", "Frz Drizzle"),
    57: ("Dense Freezing Drizzle", "🌧️", "Hvy Frz Drz"),
    61: ("Slight Rain", "🌧️", "Light Rain"),
    63: ("Moderate Rain", "🌧️", "Rain"),
    65: ("Heavy Rain", "🌧️", "Heavy Rain"),
    66: ("Light Freezing Rain", "🌧️", "Lt Frz Rain"),
    67: ("Heavy Freezing Rain", "🌧️", "Hvy Frz Rain"),
    71: ("Slight Snow", "❄️", "Light Snow"),
    73: ("Moderate Snow", "❄️", "Snow"),
    75: ("Heavy Snow", "❄️", "Heavy Snow"),
    77: ("Snow Grains", "❄️", "Snow Grains"),
    80: ("Slight Rain Showers", "🌦️", "Lt Showers"),
    81: ("Moderate Rain Showers", "🌦️", "Showers"),
    82: ("Violent Rain Showers", "🌦️", "Hvy Showers"),
    85: ("Slight Snow Showers", "🌨️", "Lt Snw Shwr"),
    86: ("Heavy Snow Showers", "🌨️", "Hvy Snw Shwr"),
    95: ("Thunderstorm", "🌩️", "T-Storm"),
    96: ("Thunderstorm w/ Slight Hail", "🌩️", "T-Storm/Hail"),
    99: ("Thunderstorm w/ Heavy Hail", "🌩️", "T-Storm/Hail"),
}


def get_wmo_info(code: int) -> Tuple[str, str, str]:
    """Returns (description, icon, short_label) for a given WMO weather code."""
    return WMO_WEATHER_CODES.get(code, ("Unknown", "🌡️", "Unknown"))


def degrees_to_cardinal(deg: Optional[float]) -> str:
    """Converts wind direction in degrees to an 8-point cardinal string (N, NE, E, etc.)."""
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int(round((deg % 360) / 45.0)) % 8
    return dirs[idx]


@dataclass
class HourlyForecastItem:
    """Represents a single hour forecast element."""
    dt_utc: datetime
    temp_f: float
    weather_code: int
    weather_desc: str
    weather_icon: str
    wind_speed_mph: float
    wind_dir_deg: float
    wind_dir_cardinal: str

    @property
    def time_display(self) -> str:
        """Formats hour into 24-hour UTC time display e.g. '14:00'."""
        return self.dt_utc.strftime("%H:%M")


@dataclass
class CurrentWeatherItem:
    """Represents current weather observations."""
    temp_f: float
    weather_code: int
    weather_desc: str
    weather_icon: str
    short_label: str
    wind_speed_mph: float
    wind_dir_deg: float
    wind_dir_cardinal: str


@dataclass
class WeatherForecastSummary:
    """Complete summary containing current conditions and 12-hour hourly forecast."""
    current: Optional[CurrentWeatherItem] = None
    hourly_forecast: List[HourlyForecastItem] = field(default_factory=list)
    home_lat: float = 0.0
    home_lon: float = 0.0
    location_name: Optional[str] = None
    fetch_time_utc: Optional[datetime] = None
    is_live: bool = False
    error_message: Optional[str] = None

    def format_tooltip_html(self) -> str:
        """Renders dark-mode GitHub-styled HTML tooltip with 12-hour forecast table and attribution."""
        lines = []
        lines.append("<div style='font-family: sans-serif; font-size: 12px; color: #e6edf3; line-height: 1.4;'>")

        if self.location_name:
            lines.append(
                f"<div style='color: #7ee787; font-size: 11px; font-weight: bold; margin-bottom: 4px;'>"
                f"📍 Location: {self.location_name}</div>"
            )

        if self.current:
            lines.append(
                f"<div style='font-size: 14px; font-weight: bold; color: #58a6ff; margin-bottom: 4px;'>"
                f"{self.current.weather_icon} Local Weather: <b>{int(round(self.current.temp_f))}°F</b> · {self.current.weather_desc}</div>"
            )
            lines.append(
                f"<div style='color: #8b949e; margin-bottom: 8px; font-size: 11px;'>"
                f"Wind: <b>{int(round(self.current.wind_speed_mph))} mph</b> from <b>{self.current.wind_dir_cardinal}</b> ({int(round(self.current.wind_dir_deg))}°)"
                f"</div>"
            )
        else:
            lines.append(
                "<div style='font-size: 14px; font-weight: bold; color: #58a6ff; margin-bottom: 4px;'>"
                "🌤️ Local Weather Forecast</div>"
            )
            if self.error_message:
                lines.append(f"<div style='color: #f85149; margin-bottom: 8px;'>Error: {self.error_message}</div>")
            else:
                lines.append("<div style='color: #8b949e; margin-bottom: 8px;'>Fetching weather data...</div>")

        # Section: 12-Hour Hourly Forecast
        if self.hourly_forecast:
            lines.append("<div style='margin-bottom: 4px;'><b>12-Hour Hourly Forecast:</b></div>")
            lines.append(
                "<table style='font-size: 11px; color: #c9d1d9; border-collapse: collapse; width: 100%; margin-left: 4px; margin-bottom: 8px;'>"
                "<tr style='color: #8b949e; border-bottom: 1px solid #30363d;'>"
                "<th style='text-align: left; padding: 2px 8px 2px 0;'>Time (UTC)</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Temp</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Condition</th>"
                "<th style='text-align: left; padding: 2px 0;'>Wind</th>"
                "</tr>"
            )
            for item in self.hourly_forecast[:12]:
                lines.append(
                    f"<tr>"
                    f"<td style='padding: 2px 8px 2px 0; color: #8b949e;'>{item.time_display}</td>"
                    f"<td style='padding: 2px 8px; color: #7ee787; font-weight: bold;'>{int(round(item.temp_f))}°F</td>"
                    f"<td style='padding: 2px 8px;'>{item.weather_icon} {item.weather_desc}</td>"
                    f"<td style='padding: 2px 0; color: #c9d1d9;'>{int(round(item.wind_speed_mph))} mph {item.wind_dir_cardinal}</td>"
                    f"</tr>"
                )
            lines.append("</table>")

        # Open-Meteo Attribution Footer
        lines.append(
            "<div style='margin-top: 6px; font-size: 10px; color: #8b949e; border-top: 1px solid #30363d; padding-top: 4px;'>"
            "Weather data provided by <b><a href='https://open-meteo.com/' style='color: #58a6ff; text-decoration: none;'>Open-Meteo.com</a></b> (CC-BY 4.0)"
            "</div>"
        )

        lines.append("</div>")
        return "".join(lines)


class WeatherEngine:
    """
    Service for querying Open-Meteo API for current weather and 12-hour hourly forecasts.
    Maintains a 15-minute in-memory cache to optimize network usage.
    """
    def __init__(self, cache_ttl_seconds: float = 900.0):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cached_summary: Optional[WeatherForecastSummary] = None
        self.last_fetch_time: Optional[datetime] = None
        self.current_lat: Optional[float] = None
        self.current_lon: Optional[float] = None

    def get_weather(
        self,
        home_lat: float,
        home_lon: float,
        location_name: Optional[str] = None,
        force_refresh: bool = False,
        timeout: int = 5,
    ) -> WeatherForecastSummary:
        """
        Retrieves weather summary for coordinates, using cache if valid.
        """
        now = datetime.now(timezone.utc)
        location_changed = (
            self.current_lat is None
            or self.current_lon is None
            or abs(self.current_lat - home_lat) > 0.05
            or abs(self.current_lon - home_lon) > 0.05
        )

        if (
            not force_refresh
            and not location_changed
            and self.cached_summary is not None
            and self.last_fetch_time is not None
            and (now - self.last_fetch_time).total_seconds() < self.cache_ttl_seconds
        ):
            if location_name:
                self.cached_summary.location_name = location_name
            return self.cached_summary

        summary = self._fetch_open_meteo(home_lat, home_lon, location_name=location_name, timeout=timeout)
        self.cached_summary = summary
        self.last_fetch_time = now
        self.current_lat = home_lat
        self.current_lon = home_lon
        return summary

    def _fetch_open_meteo(
        self, lat: float, lon: float, location_name: Optional[str] = None, timeout: int = 5
    ) -> WeatherForecastSummary:
        """Queries Open-Meteo REST API and parses JSON payload into WeatherForecastSummary."""
        summary = WeatherForecastSummary(
            home_lat=lat, home_lon=lon, location_name=location_name, fetch_time_utc=datetime.now(timezone.utc)
        )

        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m",
            "hourly": "temperature_2m,weather_code,wind_speed_10m,wind_direction_10m",
            "forecast_hours": "16",  # fetch slightly more to slice next 12 hours from current time
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "POTA-Hunter/26.8.7 (Amateur Radio Operator Tool)"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    summary.is_live = True

                    # Parse Current Weather
                    if "current" in data:
                        c_data = data["current"]
                        temp_f = float(c_data.get("temperature_2m", 0.0))
                        w_code = int(c_data.get("weather_code", 0))
                        w_speed = float(c_data.get("wind_speed_10m", 0.0))
                        w_dir = float(c_data.get("wind_direction_10m", 0.0))

                        desc, icon, short_lbl = get_wmo_info(w_code)
                        summary.current = CurrentWeatherItem(
                            temp_f=temp_f,
                            weather_code=w_code,
                            weather_desc=desc,
                            weather_icon=icon,
                            short_label=short_lbl,
                            wind_speed_mph=w_speed,
                            wind_dir_deg=w_dir,
                            wind_dir_cardinal=degrees_to_cardinal(w_dir),
                        )

                    # Parse Hourly Forecast
                    if "hourly" in data:
                        h_data = data["hourly"]
                        times = h_data.get("time", [])
                        temps = h_data.get("temperature_2m", [])
                        codes = h_data.get("weather_code", [])
                        speeds = h_data.get("wind_speed_10m", [])
                        dirs = h_data.get("wind_direction_10m", [])

                        now_utc = datetime.now(timezone.utc)
                        items: List[HourlyForecastItem] = []

                        for i in range(len(times)):
                            try:
                                # Open-Meteo returns times like "2026-08-07T14:00"
                                dt_item = datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc)
                            except Exception:
                                continue

                            # Take items starting from current hour up to 12 hours out
                            if dt_item >= now_utc or (now_utc - dt_item).total_seconds() < 3600:
                                desc, icon, _ = get_wmo_info(int(codes[i]))
                                w_cardinal = degrees_to_cardinal(float(dirs[i]))
                                items.append(
                                    HourlyForecastItem(
                                        dt_utc=dt_item,
                                        temp_f=float(temps[i]),
                                        weather_code=int(codes[i]),
                                        weather_desc=desc,
                                        weather_icon=icon,
                                        wind_speed_mph=float(speeds[i]),
                                        wind_dir_deg=float(dirs[i]),
                                        wind_dir_cardinal=w_cardinal,
                                    )
                                )
                                if len(items) >= 12:
                                    break

                        summary.hourly_forecast = items

        except Exception as e:
            logger.warning(f"Failed to fetch Open-Meteo weather data: {e}")
            summary.error_message = str(e)
            summary.is_live = False

        return summary


# Global Singleton Instance
_GLOBAL_WEATHER_ENGINE = WeatherEngine()


def fetch_local_weather_summary(
    home_lat: float,
    home_lon: float,
    location_name: Optional[str] = None,
    force_refresh: bool = False,
    timeout: int = 5,
) -> WeatherForecastSummary:
    """Convenience helper to retrieve local weather summary."""
    return _GLOBAL_WEATHER_ENGINE.get_weather(
        home_lat=home_lat,
        home_lon=home_lon,
        location_name=location_name,
        force_refresh=force_refresh,
        timeout=timeout,
    )
