"""
aurora_engine.py
Real-time NOAA SWPC OVATION Aurora Model Parser & Polyline Generator.

Fetches the latest global 30-minute auroral forecast from NOAA Space Weather
Prediction Center (SWPC) and computes smooth boundary polylines for both Northern
(Aurora Borealis) and Southern (Aurora Australis) ovals with clear visual separation.
"""

import json
import logging
import math
import time
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

SWPC_OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
CACHE_TTL_SECONDS = 600.0  # 10 minutes cache

_aurora_cache_time: float = 0.0
_aurora_cached_lines: List[Dict] = []


def _smooth_ring(d: Dict[int, float], window_size: int = 7) -> Dict[int, float]:
    """Applies a circular moving-average smoothing filter across longitude keys."""
    if len(d) < 15:
        return d
    lons = sorted(d.keys())
    n = len(lons)
    half = window_size // 2
    res = {}
    for i, lon in enumerate(lons):
        vals = [d[lons[(i + o) % n]] for o in range(-half, half + 1)]
        res[lon] = round(sum(vals) / len(vals), 2)
    return res


def _extract_oval_segments(
    coords: List[List[float]],
    hemisphere: str,
    fringe_threshold: int = 3,
    core_threshold: int = 25,
) -> Tuple[List[List[List[float]]], List[List[List[float]]]]:
    """
    Extracts continuous fringe (dashed equatorward edge) and core (solid definitive peak)
    polyline segments for a hemisphere ('north' or 'south').
    
    Returns: (fringe_segments, core_segments)
    where each segment is a list of [lat, lon] coordinates.
    """
    is_north = (hemisphere.lower() == "north")
    
    fringe_pts: Dict[int, float] = {}
    peak_pts: Dict[int, Tuple[float, int]] = {}  # lon -> (lat, max_prob)
    
    for item in coords:
        if len(item) < 3:
            continue
        lon, lat, prob = int(item[0]), float(item[1]), int(item[2])
        
        if is_north:
            if lat < 45.0:
                continue
            if prob >= fringe_threshold:
                if lon not in fringe_pts or lat < fringe_pts[lon]:
                    fringe_pts[lon] = lat
            if lon not in peak_pts or prob > peak_pts[lon][1]:
                peak_pts[lon] = (lat, prob)
        else:
            if lat > -45.0:
                continue
            if prob >= fringe_threshold:
                if lon not in fringe_pts or lat > fringe_pts[lon]:
                    fringe_pts[lon] = lat
            if lon not in peak_pts or prob > peak_pts[lon][1]:
                peak_pts[lon] = (lat, prob)

    # Core is the definitive peak activity latitude for each longitude
    core_pts: Dict[int, float] = {
        lon: lat for lon, (lat, prob) in peak_pts.items() if prob >= 2
    }
    
    # Guarantee distinct visual spacing between outer fringe and definitive core belt (minimum 4.0 degrees)
    for lon in list(fringe_pts.keys()):
        if lon in core_pts:
            if is_north:
                if core_pts[lon] - fringe_pts[lon] < 4.0:
                    fringe_pts[lon] = max(45.0, core_pts[lon] - 4.5)
            else:
                if fringe_pts[lon] - core_pts[lon] < 4.0:
                    fringe_pts[lon] = min(-45.0, core_pts[lon] + 4.5)

    # Smooth both curves for silky continuous rendering
    smooth_fringe = _smooth_ring(fringe_pts, window_size=7)
    smooth_core = _smooth_ring(core_pts, window_size=7)

    def build_segments(points_dict: Dict[int, float]) -> List[List[List[float]]]:
        if not points_dict or len(points_dict) < 3:
            return []
            
        sorted_lons = sorted(points_dict.keys())
        pts = []
        for lon in sorted_lons:
            lat = points_dict[lon]
            adj_lon = lon if lon <= 180 else lon - 360
            pts.append([round(lat, 2), round(adj_lon, 2)])
            
        pts.sort(key=lambda p: p[1])
        
        # Connect loop across antimeridian if both ends are present
        if pts and abs(pts[0][1] - (-180)) < 15 and abs(pts[-1][1] - 180) < 15:
            pts.append([pts[0][0], 180.0])
            pts.insert(0, [pts[-1][0], -180.0])

        segments = []
        curr = []
        for p in pts:
            if not curr:
                curr.append(p)
            else:
                prev_lon = curr[-1][1]
                if abs(p[1] - prev_lon) > 45.0:  # Antimeridian split
                    if len(curr) >= 2:
                        segments.append(curr)
                    curr = [p]
                else:
                    curr.append(p)
        if len(curr) >= 2:
            segments.append(curr)
        return segments

    fringe_segs = build_segments(smooth_fringe)
    core_segs = build_segments(smooth_core)
    return fringe_segs, core_segs


def fetch_ovation_aurora_lines(force_refresh: bool = False) -> List[Dict]:
    """
    Fetches the live NOAA SWPC OVATION model and generates Leaflet-compatible line objects.
    Returns list of dicts: [{"coords": segments, "style": style_dict}, ...]
    """
    global _aurora_cache_time, _aurora_cached_lines
    now = time.time()
    
    if not force_refresh and _aurora_cached_lines and (now - _aurora_cache_time < CACHE_TTL_SECONDS):
        return _aurora_cached_lines

    try:
        resp = requests.get(SWPC_OVATION_URL, timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        coords = data.get("coordinates", [])
        if not coords:
            return _aurora_cached_lines or []
            
        lines: List[Dict] = []
        
        # 1. Northern Hemisphere (Aurora Borealis)
        n_fringe, n_core = _extract_oval_segments(coords, hemisphere="north", fringe_threshold=3, core_threshold=25)
        
        if n_fringe:
            lines.append({
                "coords": n_fringe,
                "style": {"color": "#246e33", "weight": 2.0, "dashArray": "8, 6", "opacity": 0.95},
                "name": "Northern Aurora Fringe"
            })
        if n_core:
            lines.append({
                "coords": n_core,
                "style": {"color": "#144a1e", "weight": 2.8, "dashArray": "", "opacity": 1.0},
                "name": "Northern Aurora Main Belt"
            })
            
        # 2. Southern Hemisphere (Aurora Australis)
        s_fringe, s_core = _extract_oval_segments(coords, hemisphere="south", fringe_threshold=3, core_threshold=25)
        
        if s_fringe:
            lines.append({
                "coords": s_fringe,
                "style": {"color": "#246e33", "weight": 2.0, "dashArray": "8, 6", "opacity": 0.95},
                "name": "Southern Aurora Fringe"
            })
        if s_core:
            lines.append({
                "coords": s_core,
                "style": {"color": "#144a1e", "weight": 2.8, "dashArray": "", "opacity": 1.0},
                "name": "Southern Aurora Main Belt"
            })

        _aurora_cached_lines = lines
        _aurora_cache_time = now
        return lines

    except Exception as e:
        logger.warning(f"Failed to fetch NOAA OVATION aurora data: {e}")
        return _aurora_cached_lines or []
