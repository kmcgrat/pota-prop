"""
summary_engine.py
Real-time Propagation Summary & AI Prompt Generator.

Synthesizes multi-source telemetry—space weather, geomagnetic indices, D-RAP absorption,
aurora oval dynamics, meteor showers, Blitzortung lightning QRN, local weather, and
live POTA spot distributions—into a cohesive, professional narrative dispatch and
formatted LLM prompt.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional


def generate_propagation_summary(telemetry: Dict[str, Any]) -> str:
    """
    Generates a structured, professional narrative dispatch synthesizing
    all real-time telemetry from an international perspective.
    """
    now_utc = telemetry.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    grid = telemetry.get("grid") or "Unspecified"
    call = telemetry.get("my_call") or "Operator"

    solar = telemetry.get("solar_weather")
    drap = telemetry.get("drap_summary") or {}
    lightning = telemetry.get("lightning_summary") or {}
    weather = telemetry.get("weather_summary") or {}
    meteor = telemetry.get("meteor_summary") or {}
    aurora = telemetry.get("aurora_lines") or []
    spot_stats = telemetry.get("spot_stats") or {}

    sfi = getattr(solar, "sfi", 120.0) if solar else 120.0
    ssn = getattr(solar, "sunspot_number", 80) if solar else 80
    kp = getattr(solar, "k_index", 2.0) if solar else 2.0
    a_idx = getattr(solar, "a_index", 7) if solar else 7
    wind_spd = getattr(solar, "solar_wind_speed", 400.0) if solar else 400.0
    wind_dens = getattr(solar, "solar_wind_density", 5.0) if solar else 5.0
    g_scale = getattr(solar, "geomag_storm_scale", "G0") if solar else "G0"
    r_scale = getattr(solar, "radio_blackout_scale", "R0") if solar else "R0"

    lines = []
    lines.append("================================================================================")
    lines.append("PROPAGATION & OPERATING SUMMARY".center(80))
    lines.append(f"STATION: {call}  |  LOCATION: {grid}".center(80))
    lines.append("================================================================================")
    lines.append("")

    # --- 1. GLOBAL IONOSPHERIC & SOLAR SYNOPSIS ---
    lines.append(".SYNOPSIS...")
    
    # Solar Flux & Ionization evaluation
    if sfi >= 170:
        sfi_eval = f"Solar Flux Index is robust at {sfi:.0f} (SSN {ssn}), driving strong daytime F2 ionization and elevated Maximum Usable Frequencies (MUFs) globally."
    elif sfi >= 130:
        sfi_eval = f"Solar Flux Index is moderately healthy at {sfi:.0f} (SSN {ssn}), sustaining reliable daytime ionization across mid and higher HF bands."
    elif sfi >= 90:
        sfi_eval = f"Solar Flux Index is moderate at {sfi:.0f} (SSN {ssn}), offering steady daytime performance with typical seasonal MUF cutoffs."
    else:
        sfi_eval = f"Solar Flux Index is low at {sfi:.0f} (SSN {ssn}), resulting in depressed daytime MUFs and requiring focus on lower frequencies."

    # Geomagnetic evaluation
    if kp < 2.5:
        geomag_eval = f"Geomagnetic conditions are quiet and stable (Kp {kp:.1f}, Ap {a_idx}), providing low phase jitter and optimal F-layer mirror stability."
    elif kp < 3.5:
        geomag_eval = f"Geomagnetic field is unsettled (Kp {kp:.1f}, Ap {a_idx}), with minor flutter and occasional signal degradation possible on higher-latitude paths."
    elif kp < 4.5:
        geomag_eval = f"Geomagnetic activity is active (Kp {kp:.1f}, Ap {a_idx}), causing noticeable MUF depression and path fluctuations on trans-polar routes."
    elif kp < 5.5:
        geomag_eval = f"GEOMAGNETIC STORM IN PROGRESS (G1 Minor Storm, Kp {kp:.1f}, Ap {a_idx}). Expect high-latitude absorption, signal flutter on polar paths, and reduced MUF stability."
    elif kp < 6.5:
        geomag_eval = f"GEOMAGNETIC STORM IN PROGRESS (G2 Moderate Storm, Kp {kp:.1f}, Ap {a_idx}). High-latitude paths degraded with absorption spreading toward mid-latitudes."
    elif kp < 7.5:
        geomag_eval = f"MAJOR GEOMAGNETIC STORM IN PROGRESS (G3 Strong Storm, Kp {kp:.1f}, Ap {a_idx}). Widespread HF absorption, severe flutter fading, and depressed MUFs."
    elif kp < 8.5:
        geomag_eval = f"SEVERE GEOMAGNETIC STORM IN PROGRESS (G4 Severe Storm, Kp {kp:.1f}, Ap {a_idx}). Wide-area HF degradation and polar blackout."
    else:
        geomag_eval = f"EXTREME GEOMAGNETIC STORM IN PROGRESS (G5 Extreme Storm, Kp {kp:.1f}, Ap {a_idx}). Widespread HF blackout across major portions of the globe."

    # Solar Wind evaluation
    wind_eval = f"Solar wind velocity is currently {wind_spd:.0f} km/s with a proton density of {wind_dens:.1f} p/cm³."
    if wind_spd > 550:
        wind_eval += " Elevated wind speeds suggest coronal hole high-speed stream interaction with Earth's magnetosphere."

    # D-RAP / Solar Flares
    drap_loss = drap.get("highest_absorption_db", 0.0) if isinstance(drap, dict) else 0.0
    if drap_loss > 3.0 or (r_scale and r_scale != "R0"):
        drap_eval = f"D-Region solar X-ray absorption is elevated ({r_scale}, ~{drap_loss:.1f} dB on lower HF) across the sunlit hemisphere."
    else:
        drap_eval = "D-Region solar X-ray absorption remains at baseline quiet levels across sunlit longitudes."

    lines.append(f"{sfi_eval} {geomag_eval} {wind_eval} {drap_eval}")
    lines.append("")

    # --- 2. BAND-BY-BAND CONDITIONS & OUTLOOK ---
    lines.append(".BAND CONDITIONS & OPERATING OUTLOOK...")

    # High HF (10m, 12m, 15m)
    if sfi >= 140 and kp < 4.0:
        high_hf_str = "10m, 12m, and 15m are offering excellent daytime F2 openings with low background noise. Trans-equatorial and continental paths are wide open during peak sunlit hours."
    elif sfi >= 100:
        high_hf_str = "15m and 12m are dependable during sunlit hours; 10m is experiencing selective openings with sporadic enhancements."
    else:
        high_hf_str = "10m and 12m are quiet with infrequent openings; 15m provides intermittent daytime paths under lower solar flux."
    lines.append(f"* HIGHER HF (10m - 15m): {high_hf_str}")

    # Mid HF (17m, 20m)
    if kp < 4.0:
        mid_hf_str = "20m and 17m remain premier all-around workhorses, delivering strong continental signals and consistent DX reach throughout daylight and twilight transitions."
    else:
        mid_hf_str = "20m and 17m remain active, though elevated geomagnetic activity may introduce QSB (flutter fading) on trans-auroral and high-latitude paths."
    lines.append(f"* MID HF (17m - 20m): {mid_hf_str}")

    # Lower HF (30m, 40m, 60m, 80m, 160m)
    low_hf_str = "40m and 30m provide solid daytime NVIS and regional coverage out to 400-600 miles (650-1000 km), extending to long-haul continental range after local dusk. 80m and 160m are optimal for night-time regional communications."
    lines.append(f"* LOWER HF (30m - 160m): {low_hf_str}")

    # VHF (6m, 2m)
    vhf_notes = []
    if meteor and meteor.get("active_showers"):
        showers_str = ", ".join(meteor.get("active_showers", []))
        vhf_notes.append(f"Meteor scatter bursts supported by {showers_str} (ZHR ~{meteor.get('peak_zhr', 10)}).")
    if kp >= 4.5:
        vhf_notes.append("Elevated Kp indicates potential for 6m/2m auroral backscatter/reflection in sub-polar regions.")
    if not vhf_notes:
        vhf_notes.append("Tropospheric and line-of-sight conditions prevailing; monitor 6m for occasional Sporadic-E openings.")
    lines.append(f"* VHF (6m - 2m): {' '.join(vhf_notes)}")
    lines.append("")

    # --- 3. SHORT-TERM 3-DAY & EXTENDED 27-DAY FORECAST OUTLOOK ---
    forecast_3day = getattr(solar, "forecast_3day", None) if solar else None
    outlook_27day = getattr(solar, "outlook_27day", None) if solar else None

    if forecast_3day and getattr(forecast_3day, "days", None) and len(forecast_3day.days) >= 3:
        d1, d2, d3 = forecast_3day.days[0], forecast_3day.days[1], forecast_3day.days[2]
        s1, s2, s3 = forecast_3day.sfi_forecast[0], forecast_3day.sfi_forecast[1], forecast_3day.sfi_forecast[2]
        ap1, ap2, ap3 = forecast_3day.ap_forecast[0], forecast_3day.ap_forecast[1], forecast_3day.ap_forecast[2]
        k1, k2, k3 = forecast_3day.kp_max_forecast[0], forecast_3day.kp_max_forecast[1], forecast_3day.kp_max_forecast[2]
        m1, m2, m3 = forecast_3day.m_flare_prob[0], forecast_3day.m_flare_prob[1], forecast_3day.m_flare_prob[2]
        g1, g2, g3 = forecast_3day.geomag_scale[0], forecast_3day.geomag_scale[1], forecast_3day.geomag_scale[2]

        lines.append(".SHORT-TERM 3-DAY PROPAGATION OUTLOOK (NOAA SWPC)...")

        if s2 > s1 + 3:
            sfi_narrative = f"Solar flux is projected to rise from {s1:.0f} to {s2:.0f} sfu, boosting daytime F2 ionization and expanding daytime 15m/10m openings."
        elif s2 < s1 - 3:
            sfi_narrative = f"Solar flux is projected to ease slightly from {s1:.0f} to {s2:.0f} sfu, maintaining steady daytime baseline performance across 20m and 17m."
        else:
            sfi_narrative = f"Solar flux is projected to remain steady near {s1:.0f}-{s2:.0f} sfu ({d1}-{d3}), sustaining reliable daytime F2 propagation across 20m, 17m, and 15m."
        lines.append(f"* SOLAR FLUX & F2 IONIZATION: {sfi_narrative}")

        if max(k1, k2, k3) >= 5.0 or any("G1" in g for g in (g1, g2, g3)):
            active_g = g1 if "G1" in g1 else (g2 if "G1" in g2 else g3)
            geomag_narrative = f"Geomagnetic activity elevates to {active_g} (peak Kp {max(k1,k2,k3):.1f}, Ap {max(ap1,ap2,ap3)}). Expect path flutter and degraded high-latitude / trans-polar signals."
        elif max(k1, k2, k3) >= 3.5:
            geomag_narrative = f"Geomagnetic field will be unsettled at times ({d1}: Kp {k1:.1f}, {d2}: Kp {k2:.1f}, {d3}: Kp {k3:.1f}; Ap {ap1}->{ap2}->{ap3}), with minor flutter on polar routes while mid-latitude paths remain stable."
        else:
            geomag_narrative = f"Geomagnetic field conditions remain quiet and stable across the period ({d1}: Kp {k1:.1f}, {d2}: Kp {k2:.1f}, {d3}: Kp {k3:.1f}; Ap {ap1}-{ap3}), providing optimal ionospheric mirror stability."
        lines.append(f"* GEOMAGNETIC STABILITY & POLAR PATHS: {geomag_narrative}")

        max_m = max(m1, m2, m3)
        if max_m >= 40:
            flare_narrative = f"M-Class flare probability is elevated at {max_m}% ({d1}: {m1}%, {d2}: {m2}%, {d3}: {m3}%). Daytime operators should monitor for brief D-RAP absorption fadeouts on sunlit lower HF paths. Proton storm risk is low ({forecast_3day.proton_prob[0]}%)."
        else:
            flare_narrative = f"M-Class flare probability remains low to moderate ({m1}% / {m2}% / {m3}%). Minimal solar X-ray absorption expected across sunlit longitudes. Proton storm risk is nominal (<1%)."
        lines.append(f"* SOLAR FLARE & ABSORPTION HAZARDS: {flare_narrative}")
        lines.append("")

    if outlook_27day and getattr(outlook_27day, "daily_projections", None):
        lines.append(".EXTENDED 27-DAY SOLAR CYCLE & RECURRENT OUTLOOK...")
        lines.append(f"* 27-DAY SOLAR FLUX TREND: 7-day average SFI is projected at ~{outlook_27day.sfi_7day_avg:.0f} sfu. Optimum upper-band DX window: {outlook_27day.sfi_peak_window}.")
        lines.append(f"* RECURRENT GEOMAGNETIC STORMS: {outlook_27day.recurrent_storm_window}.")
        lines.append("")

    # --- 4. SPACE WEATHER, AURORA & METEORS ---
    lines.append(".SPACE WEATHER & SPECIAL PHENOMENA...")
    if aurora:
        lines.append(f"* AURORAL OVAL: Real-time NOAA SWPC model indicates auroral activity active in polar zones. Equatorward fringe and core peak belts are plotted on the live map.")
    else:
        lines.append("* AURORAL OVAL: Polar activity remains confined to high geomagnetic latitudes with minimal mid-latitude degradation.")

    if meteor and meteor.get("active_showers"):
        lines.append(f"* METEORS: Active showers include {', '.join(meteor.get('active_showers', []))} with estimated peak Zenithal Hourly Rate (ZHR) of {meteor.get('peak_zhr', 15)}.")
    else:
        lines.append("* METEORS: Background sporadic meteor flux present with routine early-morning scatter enhancement.")
    lines.append("")

    # --- 4. LOCAL QRN & THUNDERSTORM HAZARDS ---
    lines.append(".LOCAL QRN & THUNDERSTORM HAZARDS...")
    strikes_100 = lightning.get("strikes_100km", 0) if isinstance(lightning, dict) else 0
    strikes_300 = lightning.get("strikes_300km", 0) if isinstance(lightning, dict) else 0
    closest_km = lightning.get("closest_km", 999.0) if isinstance(lightning, dict) else 999.0

    if strikes_100 > 0:
        lines.append(f"* REAL-TIME LIGHTNING ALERT: ACTIVE CONVECTION. {strikes_100} strikes recorded within 100 km (closest strike ~{closest_km:.1f} km / {closest_km*0.621371:.1f} mi).")
        lines.append("  Expect severe static crashes (QRN) on 160m, 80m, and 40m. Outdoor operators should monitor weather radar and follow station lightning safety protocols.")
    elif strikes_300 > 0:
        lines.append(f"* REAL-TIME REGIONAL LIGHTNING: {strikes_300} strikes detected within 300 km (closest strike ~{closest_km:.1f} km / {closest_km*0.621371:.1f} mi).")
        lines.append("  Moderate static discharges may affect lower HF bands (80m/40m). Higher HF bands (20m-10m) remain clean.")
    else:
        lines.append("* REAL-TIME STRIKE PROXIMITY: No significant lightning activity detected within 300 km of your QTH. Low local static noise floors expected across all bands.")

    # 3-Day Convective & QRN Outlook
    conv_3day = weather.get("convective_3day") if isinstance(weather, dict) else None
    if conv_3day and getattr(conv_3day, "days", None):
        lines.append("* 3-DAY CONVECTIVE & QRN OUTLOOK (GLOBAL GFS/ECMWF):")
        for idx, cday in enumerate(conv_3day.days, 1):
            lines.append(
                f"  - DAY {idx} ({cday.day_date}): {cday.precip_prob_max}% Rain / {cday.thunderstorm_prob}% Thunderstorm Risk "
                f"(CAPE {cday.max_cape:.0f} J/kg, {cday.weather_desc}). {cday.qrn_risk}."
            )

    # Seasonal QRN Climatology
    from weather_engine import get_seasonal_qrn_climatology
    station_lat = 40.0  # default temperate northern
    if isinstance(weather, dict) and weather.get("home_lat") is not None:
        station_lat = float(weather["home_lat"])
    elif len(grid) >= 2 and grid[1].isalpha():
        station_lat = (ord(grid[1].upper()) - ord('A')) * 10 - 90 + 5.0
    
    climatology = get_seasonal_qrn_climatology(station_lat)
    lines.append(f"* SEASONAL QRN CLIMATOLOGY: {climatology}")

    if weather and weather.get("temperature_c") is not None:
        temp_c = weather.get("temperature_c")
        temp_f = temp_c * 9/5 + 32 if temp_c is not None else 0
        press = weather.get("pressure_hpa", 1013)
        wind_kph = weather.get("wind_speed_kph", 0)
        lines.append(f"* LOCAL WEATHER: {temp_c:.1f}°C ({temp_f:.1f}°F), Barometric Pressure: {press:.1f} hPa, Wind: {wind_kph:.1f} km/h.")
    lines.append("")

    # --- 5. LIVE POTA ACTIVITY & HOTSPOTS ---
    lines.append(".POTA ACTIVITY & PROPAGATION HOTSPOTS...")
    total_spots = spot_stats.get("total_active_spots", 0)
    band_counts = spot_stats.get("band_counts", {})
    top_regions = spot_stats.get("top_regions", [])

    if total_spots > 0:
        lines.append(f"* ACTIVE ACTIVATIONS: {total_spots} park activations currently on the air worldwide.")
        if band_counts:
            sorted_bands = sorted(band_counts.items(), key=lambda x: x[1], reverse=True)
            band_str = ", ".join([f"{b}: {c} parks" for b, c in sorted_bands[:4]])
            lines.append(f"* BAND DISTRIBUTION: {band_str}.")
        if top_regions:
            region_str = ", ".join([f"{r} ({c})" for r, c in top_regions[:5]])
            lines.append(f"* REGIONAL HOTSPOTS: Heavy activity concentrated in {region_str}.")
    else:
        lines.append("* ACTIVE ACTIVATIONS: Monitoring live spot feed for incoming activations.")
    lines.append("")

    # --- 6. RECOMMENDED OPERATING STRATEGY ---
    lines.append(".RECOMMENDED OPERATING STRATEGY...")
    strat = []
    if sfi >= 120 and kp < 4.0:
        strat.append("Focus on 20m and 15m for maximum continental and DX reach with optimal signal-to-noise ratios.")
    else:
        strat.append("Rely on 20m and 40m as core primary bands to ensure consistent contact volume.")

    if strikes_100 > 0 or strikes_300 > 50:
        strat.append("Engage receiver Noise Blanker (NB) or DSP digital filtering if operating on 40m/80m due to regional lightning QRN.")
    else:
        strat.append("Noise floors on 40m/30m/20m are favorable for QRP and portable park hunting.")

    if total_spots > 10:
        strat.append(f"Take advantage of high park density across active frequencies to maximize hunter QSO rates.")

    lines.append(" ".join(strat))
    lines.append("================================================================================")

    return "\n".join(lines)
