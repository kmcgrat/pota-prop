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
from typing import List, Optional, Tuple
import urllib.request
import urllib.parse

logger = logging.getLogger(__name__)

# WMO Weather Interpretation Codes (WW) mapping to (Description, Emoji/Icon, Short Label)
WMO_WEATHER_CODES = {
    0: ("Clear Sky", "", "Clear"),
    1: ("Mainly Clear", "", "Mainly Clear"),
    2: ("Partly Cloudy", "", "Partly Cloudy"),
    3: ("Overcast", "", "Overcast"),
    45: ("Foggy", "", "Fog"),
    48: ("Depositing Rime Fog", "", "Rime Fog"),
    51: ("Light Drizzle", "", "Light Drizzle"),
    53: ("Moderate Drizzle", "", "Drizzle"),
    55: ("Dense Drizzle", "", "Heavy Drizzle"),
    56: ("Light Freezing Drizzle", "", "Frz Drizzle"),
    57: ("Dense Freezing Drizzle", "", "Hvy Frz Drizzle"),
    61: ("Slight Rain", "", "Light Rain"),
    63: ("Moderate Rain", "", "Rain"),
    65: ("Heavy Rain", "", "Heavy Rain"),
    66: ("Light Freezing Rain", "", "Light Frz Rain"),
    67: ("Heavy Freezing Rain", "", "Heavy Frz Rain"),
    71: ("Slight Snow", "", "Light Snow"),
    73: ("Moderate Snow", "", "Snow"),
    75: ("Heavy Snow", "", "Heavy Snow"),
    77: ("Snow Grains", "", "Snow Grains"),
    80: ("Slight Rain Showers", "", "Light Showers"),
    81: ("Moderate Rain Showers", "", "Showers"),
    82: ("Violent Rain Showers", "", "Heavy Showers"),
    85: ("Slight Snow Showers", "", "Light Snow Shwr"),
    86: ("Heavy Snow Showers", "", "Heavy Snow Shwr"),
    95: ("Thunderstorm", "", "T-Storm"),
    96: ("Thunderstorm w/ Slight Hail", "", "T-Storm / Hail"),
    99: ("Thunderstorm w/ Heavy Hail", "", "T-Storm / Hail"),
}


def get_wmo_info(code: int) -> Tuple[str, str, str]:
    """Returns (description, icon, short_label) for a given WMO weather code."""
    return WMO_WEATHER_CODES.get(code, ("Unknown", "", "Unknown"))


def degrees_to_cardinal(deg: Optional[float]) -> str:
    """Converts wind direction in degrees to an 8-point cardinal string (N, NE, E, etc.)."""
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = round((deg % 360) / 45.0) % 8
    return dirs[idx]


@dataclass
class HourlyForecastItem:
    """Represents a single hour forecast element."""
    dt_utc: datetime
    temp_f: float
    precip_prob: int
    weather_code: int
    weather_desc: str
    weather_icon: str
    wind_speed_mph: float
    wind_dir_deg: float
    wind_dir_cardinal: str
    humidity_pct: int

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
    humidity_pct: int


@dataclass
class ConvectiveDayForecast:
    """Represents convective storm and QRN static outlook for a single day."""
    day_date: str
    precip_prob_max: int
    thunderstorm_prob: int
    max_cape: float
    weather_code: int
    weather_desc: str
    qrn_risk: str


@dataclass
class Convective3DayForecast:
    """3-day convective thunderstorm and QRN forecast."""
    days: List[ConvectiveDayForecast] = field(default_factory=list)


@dataclass
class WeatherForecastSummary:
    """Complete summary containing current conditions, 12-hour hourly forecast, and 3-day convective outlook."""
    current: Optional[CurrentWeatherItem] = None
    hourly_forecast: List[HourlyForecastItem] = field(default_factory=list)
    convective_3day: Optional[Convective3DayForecast] = None
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
                f"Location: {self.location_name}</div>"
            )

        if self.current:
            lines.append(
                f"<div style='font-size: 14px; font-weight: bold; color: #58a6ff; margin-bottom: 4px;'>"
                f"{self.current.weather_icon} Local Weather: <b>{round(self.current.temp_f)}°F</b> · {self.current.weather_desc}</div>"
            )
            lines.append(
                f"<div style='color: #8b949e; margin-bottom: 8px; font-size: 11px;'>"
                f"Wind: <b>{round(self.current.wind_speed_mph)} mph</b> from <b>{self.current.wind_dir_cardinal}</b> ({round(self.current.wind_dir_deg)}°) | Humidity: <b>{self.current.humidity_pct}%</b>"
                f"</div>"
            )
        else:
            lines.append(
                "<div style='font-size: 14px; font-weight: bold; color: #58a6ff; margin-bottom: 4px;'>"
                "Local Weather Forecast</div>"
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
                "<th style='text-align: left; padding: 2px 8px;'>Hum</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Precip</th>"
                "<th style='text-align: left; padding: 2px 8px;'>Condition</th>"
                "<th style='text-align: left; padding: 2px 0;'>Wind</th>"
                "</tr>"
            )
            for item in self.hourly_forecast[:12]:
                lines.append(
                    f"<tr>"
                    f"<td style='padding: 2px 8px 2px 0; color: #8b949e;'>{item.time_display}</td>"
                    f"<td style='padding: 2px 8px; color: #7ee787; font-weight: bold;'>{round(item.temp_f)}°F</td>"
                    f"<td style='padding: 2px 8px; color: #58a6ff;'>{item.humidity_pct}%</td>"
                    f"<td style='padding: 2px 8px; color: #79c0ff;'>{item.precip_prob}%</td>"
                    f"<td style='padding: 2px 8px;'>{item.weather_icon} {item.weather_desc}</td>"
                    f"<td style='padding: 2px 0;'>{round(item.wind_speed_mph)} mph {item.wind_dir_cardinal}</td>"
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
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
            "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m,cape",
            "daily": "weather_code,precipitation_probability_max",
            "forecast_days": "3",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "POTA-Hunter/26.8.17-6 (Amateur Radio Operator Tool)"}
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
                        humidity_pct = int(c_data.get("relative_humidity_2m", 0))

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
                            humidity_pct=humidity_pct,
                        )

                    # Parse Hourly Forecast
                    if "hourly" in data:
                        h_data = data["hourly"]
                        times = h_data.get("time", [])
                        temps = h_data.get("temperature_2m", [])
                        precips = h_data.get("precipitation_probability", [])
                        codes = h_data.get("weather_code", [])
                        speeds = h_data.get("wind_speed_10m", [])
                        dirs = h_data.get("wind_direction_10m", [])
                        hums = h_data.get("relative_humidity_2m", [])

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
                                precip_val = int(precips[i]) if i < len(precips) else 0
                                items.append(
                                    HourlyForecastItem(
                                        dt_utc=dt_item,
                                        temp_f=float(temps[i]),
                                        precip_prob=precip_val,
                                        weather_code=int(codes[i]),
                                        weather_desc=desc,
                                        weather_icon=icon,
                                        wind_speed_mph=float(speeds[i]),
                                        wind_dir_deg=float(dirs[i]),
                                        wind_dir_cardinal=w_cardinal,
                                        humidity_pct=int(hums[i]) if i < len(hums) else 0,
                                    )
                                )
                        summary.hourly_forecast = items

                    # Parse 3-Day Convective / Thunderstorm Forecast
                    if "daily" in data:
                        d_data = data["daily"]
                        d_times = d_data.get("time", [])
                        d_codes = d_data.get("weather_code", [])
                        d_precips = d_data.get("precipitation_probability_max", [])

                        # Calculate daily max CAPE from hourly if present
                        h_capes = data.get("hourly", {}).get("cape", []) if "hourly" in data else []
                        h_times = data.get("hourly", {}).get("time", []) if "hourly" in data else []

                        conv_days: List[ConvectiveDayForecast] = []
                        for di in range(min(3, len(d_times))):
                            dt_str = d_times[di]
                            wcode = int(d_codes[di]) if di < len(d_codes) else 0
                            pprob = int(d_precips[di]) if di < len(d_precips) else 0
                            wdesc, _, _ = get_wmo_info(wcode)

                            # Find max CAPE for this day
                            day_capes = [
                                float(h_capes[hi])
                                for hi in range(len(h_capes))
                                if hi < len(h_times) and h_times[hi].startswith(dt_str) and h_capes[hi] is not None
                            ]
                            max_cape = max(day_capes) if day_capes else 0.0

                            # Estimate thunderstorm probability based on WMO code, Precip %, and CAPE
                            is_ts_code = wcode in (95, 96, 99)
                            if is_ts_code:
                                ts_prob = max(60, pprob)
                            elif max_cape >= 2000:
                                ts_prob = min(80, int(pprob * 0.9))
                            elif max_cape >= 1000:
                                ts_prob = min(60, int(pprob * 0.7))
                            elif max_cape >= 500:
                                ts_prob = min(40, int(pprob * 0.5))
                            else:
                                ts_prob = min(20, int(pprob * 0.2))

                            # QRN impact rating
                            if ts_prob >= 50 or is_ts_code or max_cape >= 1500:
                                qrn_risk = "Elevated QRN risk (+10 to +18 dB static crash surges on 40m-160m)"
                            elif ts_prob >= 25 or max_cape >= 600:
                                qrn_risk = "Moderate QRN (occasional distant static crashes during peak heating)"
                            else:
                                qrn_risk = "Quiet baseline noise floor across all HF bands"

                            # Format friendly date (e.g. "Aug 18")
                            try:
                                parsed_d = datetime.strptime(dt_str, "%Y-%m-%d")
                                friendly_d = parsed_d.strftime("%b %d")
                            except Exception:
                                friendly_d = dt_str

                            conv_days.append(
                                ConvectiveDayForecast(
                                    day_date=friendly_d,
                                    precip_prob_max=pprob,
                                    thunderstorm_prob=ts_prob,
                                    max_cape=round(max_cape, 1),
                                    weather_code=wcode,
                                    weather_desc=wdesc,
                                    qrn_risk=qrn_risk,
                                )
                            )

                        if conv_days:
                            summary.convective_3day = Convective3DayForecast(days=conv_days)

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


def get_seasonal_qrn_climatology(lat: float, month: Optional[int] = None) -> str:
    """
    Computes global seasonal atmospheric noise (QRN) and lightning climatology
    based on station latitude and current month.
    """
    if month is None:
        month = datetime.now(timezone.utc).month

    # Northern Hemisphere (> 20 deg N)
    if lat >= 20.0:
        if month in (8, 9):  # Late Summer -> Autumn
            return (
                "Northern temperate latitudes are transitioning from peak summer convection into autumn. "
                "Regional lightning strike frequency drops by ~35-50% over the coming weeks, leading to a "
                "steady reduction in baseline atmospheric crash noise on 80m and 160m."
            )
        elif month in (10, 11, 12, 1, 2):  # Late Autumn -> Winter
            return (
                "Northern winter low-QRN baseline prevailing. Cold, stable continental air suppresses regional "
                "thunderstorm activity, delivering prime DX operating conditions and minimum receiver noise on 160m, 80m, and 40m."
            )
        elif month in (3, 4, 5):  # Spring
            return (
                "Northern spring convective ramp-up in progress. Increasing solar insolation and frontal activity "
                "gradually elevate diurnal static noise and sporadic thunderstorm clusters across mid-latitudes."
            )
        else:  # June, July (Peak Summer)
            return (
                "Northern hemisphere mid-summer peak convective season. Intense solar heating drives diurnal "
                "thunderstorm development; expect persistent elevated QRN (S5-S7) and frequent static crashes on 160m-40m until local midnight."
            )

    # Southern Hemisphere (< -20 deg S)
    elif lat <= -20.0:
        if month in (8, 9, 10):  # Late Winter -> Spring
            return (
                "Southern temperate latitudes are transitioning into spring. Solar heating is increasing convective "
                "instability across South America, Southern Africa, and Australia, beginning a seasonal rise in lower-HF static noise."
            )
        elif month in (11, 12, 1, 2):  # Summer Peak
            return (
                "Southern hemisphere summer convective peak. Diurnal heating generates frequent thunderstorm clusters, "
                "elevating 80m/160m noise floors during evening and nighttime operating hours."
            )
        elif month in (3, 4, 5):  # Autumn
            return (
                "Southern hemisphere autumn transition. Diurnal thunderstorm activity is diminishing, yielding "
                "progressively quieter noise baselines and improving lower-HF DX conditions."
            )
        else:  # Winter (June, July)
            return (
                "Southern winter low-QRN window active. Stable atmospheric conditions minimize local lightning, "
                "providing optimal receiver sensitivity on 40m, 80m, and 160m."
            )

    # Tropical / Equatorial Belt (-20 deg to +20 deg)
    else:
        return (
            "Equatorial / Tropical maritime zone. Persistent Intertropical Convergence Zone (ITCZ) convection maintains "
            "year-round elevated atmospheric noise levels (S5-S8) on 160m, 80m, and 40m, peaking during local late afternoon and dusk."
        )
