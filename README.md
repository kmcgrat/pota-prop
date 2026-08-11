# POTA Prop

A desktop GUI application built in Python and PyQt6 for amateur radio operators participating in **Parks on the Air (POTA)**.

It compares your historical hunted parks export against live active spots on [pota.app](https://pota.app), highlighting which active activators represent **NEW (unhunted)** parks versus parks you have already worked, and calculates an estimated **QSO Success Probability (Score)** based on ionospheric propagation modeling, ray tracing, skip-zone physics, live space weather, and regional lightning noise (QRN).

---

## Key Features

- **Live POTA Spot Synchronization**: Asynchronously fetches active spots from `https://api.pota.app/spot/activator` with configurable auto-refresh intervals (Manual, 30s, 1m, 2m, 5m).
- **HF/VHF Propagation & QSO Score Modeling**:
  - **Multi-Layer Ionospheric Profile (E, F1, F2)**: Computes Chapman solar-zenith electron density for E/F1 layers and diurnal variation for the F2 layer ($foE, hmE, foF1, hmF1, foF2, hmF2, ymF2$).
  - **Multi-Hop Ray Tracing ($1E, 2E, 1F2, 2F2, 3F2, 4F2$)**: Calculates takeoff launch elevation angles ($\Delta$) and ionospheric incidence angles ($\phi_{\text{inc}}$) across Great-Circle paths to identify the dominant ray path mode.
  - **Skip-Zone Calculations**: Evaluates oblique critical frequency ($f \le foF2 \sec \phi_{\text{inc}}$). If an operating frequency exceeds the oblique MUF on short skip or nighttime paths, the path is flagged as closed.
  - **Global DXCC & Region Mapping**: Automatically resolves international DXCC entities (US, Canada, Europe, Oceania, etc.) using local prefix and geolocation context for realistic global verification bonuses.
  - **Regional Lightning & Convective Threat Engine**: Hybrid architecture combining instant **NOAA NWS Convective Alerts** (Severe Thunderstorm, Tornado, Marine, Flash Flood warnings with active popup alerts) with real-time **Blitzortung.org** live WebSocket stroke telemetry across a 750-mile radius. Features **Storm Cell Trajectory Tracking** deriving ground speed (mph), cardinal movement direction, and **Time of Arrival (TOA in minutes)** estimates for approaching storms. Features a 1-to-10 threat scale, station safety advisories (Level 9/10 feedline disconnect alerts), and frequency-dependent noise surge ($\Delta F_{\text{QRN}}$) modeling.
  - **Open-Meteo Local Weather & 12-Hour Hourly Forecast**: Top dashboard card displaying current temperature and weather condition icon (`72°F ⛅`). Mouseover popup opens a 12-hour hourly forecast table with **Time (UTC)** in 24-hour format, temperature (°F), weather condition icons/descriptions, wind vectors, and Open-Meteo attribution.
  - **Receiver Band Noise Floor Matrix (ITU-R P.372-16)**: Full 11-band noise floor engine (160m to 6m) modeling diurnal day/night atmospheric noise curves, cosmic/galactic background, man-made baselines, and live Blitzortung lightning QRN surges with standard IARU S-meter calibration ($S9 = -73\text{ dBm}$, $6\text{ dB/S-unit}$). Accessible via top dashboard stat card or **F6** hotkey.
  - **Station Link Budget & SNR Estimation**: Incorporates transmitter power (Watts to dBW), antenna radiation patterns (Dipole, End-Fed, Vertical, Loop, Random Wire, 3-Element Beam), free-space path loss ($L_{\text{bf}}$), ionospheric absorption ($L_a$) with geomagnetic gyrofrequency ($f_H = 1.4\text{ MHz}$), and ground reflection losses ($L_g$).
  - **Live Space Weather**: Background worker pulls 10.7cm Solar Flux Index (SFI), planetary K-index, planetary A-index, and GOES Satellite 0.1–0.8nm X-ray flux (solar flare monitoring R1–R5) from NOAA SWPC.
  - **Automated QRT Detection & Real-Time Decodes**: Adjusts QSO Score when spot comments indicate an activator is QRT (off the air), and adds score adjustments (+15) for PSKReporter and WSPR live decodes.
  - **Grayline Enhancement**: Applies path adjustments when either endpoint or the path midpoint aligns with the solar terminator.
  - **VHF/UHF Line-of-Sight & 6m Es Modeling**: Bounds 2m/70cm to tropospheric line-of-sight range (~150 km max) and detects summer Sporadic-E skip paths for 6m.
- **Interactive Multi-Filter Controls**:
  - **Status Filter**: View *All*, *New*, *Hunted*, *Worked*, or *P2P*.
  - **QSO Score Filter**: Filter by *All (0+)*, *>= 25 (Possible)*, *>= 50 (Good)*, *>= 75 (High)*, or *>= 99 (Exceptional)*.
  - **Band Filter**: Filter by 160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 2m, 70cm, etc.
  - **Mode Filter**: Filter by CW, SSB, FT8, FT4, FM, AM, Digital, etc.
  - **Instant Search**: Real-time search across Park ID, Park Name, Activator Callsign, Location/State, Grid, or Spotter Comments.
- **Summary Metric Cards**: Live counters for Unhunted Spots, Hunted Spots, Total Spots, Unique Active Parks, Total Parks in Log, Live NOAA Space Weather (SFI / K-Index), Regional Lightning Activity (1–10 Threat Scale), and Receiver Band Noise Floor (S-units).
- **Interactive Table & Resizable Columns**:
  - **13 Detailed Columns**: Status, `Score`, Activator, Frequency, Time, Park ID, Park Name, Location/State, Band, Mode, Distance & Bearing, Grid, Comments.
  - **Local Verification (`+` Symbol)**: Scores featuring a `+` (e.g. `85+`) indicate local spotter verification confirming nearby spotters in your region hear the signal.
  - **Interactive Diagnostics**: Hover over any `Score` badge or table row to see full path diagnostics (Ray Mode, Launch Angle, Path Loss, Predicted SNR, MUF, Lightning QRN Surge, Space Weather).
  - **Adjustable Column Widths**: Drag any column header boundary to resize columns.
  - **Auto-Fit & Reset**: Right-click any column header to access `Auto-fit All Column Widths` or `Reset Column Widths to Default`.
  - **Persistent Layout**: Custom column widths, window geometry, and home grid are automatically saved and restored across sessions.
  - **Double-click any row** to open the Spot Intelligence & Respot History window.
  - **Right-click context menu (rows)**:
    - Open Park on pota.app
    - Look up Activator Callsign on QRZ.com
    - Copy Park Reference, Callsign, Frequency, or Full Details to clipboard
    - Quick-filter table by Activator or Park
    - Toggle Worked Status
- **Export**: Export filtered table view (including Score, SNR, Ray Mode, Distance/Bearing) to CSV.

---

## First-Time Setup Guide

1. **Authenticate and Sync Data from POTA.app**:
   - Click **Sign In POTA.app** in the application. A secure browser window will open, allowing you to sign into your pota.app account.
   - Once authenticated, click **Sync POTA Data**. POTA Prop will automatically connect to the POTA API, download your entire historical hunted log, and integrate it instantly. No more downloading CSV files manually!
2. **Configure Your Station**:
   - Enter your **My Call** and **Home Grid** (e.g. `EM98dh`).
   - Select your transmitter power (5W, 100W, 500W, 1500W) and antenna preset (Dipole, Vertical, Beam, etc.) to tailor the link budget.
3. **Marking Worked Parks Off Your List**:
   - Made a contact with an active park? Click the **Status** drop-down menu in the table row and select **Mark [WORKED]** (or right-click the row and select *Toggle Worked Status*).
   - The row immediately turns green, and your counters update. Manually worked parks are saved persistently across sessions!

---

## How to Run

### Quick Launch
From the terminal, run the launcher script:
```bash
cd /path/to/POTA
./run.sh
```

Or execute directly with Python:
```bash
python3 pota_hunter.py
```

---

## Dependencies

- Python 3.10+
- `PyQt6`
- `PyQt6-WebEngine`
- `requests`

Installed automatically in the Python environment. To install in a separate environment:
```bash
pip install -r requirements.txt
```

---

## Running Automated Tests

Run the test suite:
```bash
python3 test_pota_hunter.py
```

---

## Author & Acknowledgements

- **Designed & Tested by:** Kevin McGrath (**W7KMC**) for the Amateur Radio and Parks on the Air (POTA) community.
- **Data & Service Acknowledgements:** [pota.app](https://pota.app), [Blitzortung.org](https://www.blitzortung.org) Community Lightning Network, [Open-Meteo.com](https://open-meteo.com/) Weather API, NOAA Space Weather Prediction Center (SWPC).

---

## Safety Disclaimer & Limitation of Liability

**FOR RECREATIONAL & INFORMATIONAL AMATEUR RADIO USE ONLY**

POTA Prop is provided strictly for recreational amateur radio operating, propagation modeling, and educational interest. All weather forecasts, lightning cluster motion tracking, Time of Arrival (TOA) estimates, NOAA NWS convective alert warnings, band noise calculations, and ionospheric propagation scores are generated by automated computer models and third-party network feeds.

**THIS SOFTWARE MUST NEVER BE RELIED UPON FOR LIFE SAFETY, WEATHER HAZARD PREDICTION, LIGHTNING PROTECTION, OR EMERGENCY FIELD PLANNING.**

Severe weather, lightning strikes, electrostatic discharges, and atmospheric conditions can change, intensify, or strike rapidly without warning or detection by remote sensors. Amateur radio operators operating portable in parks or at fixed station locations are solely responsible for maintaining situational awareness, observing local environmental conditions, and taking appropriate safety precautions (including immediately shutting down, disconnecting antenna feedlines, grounding equipment, and seeking proper shelter during lightning activity).

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. IN NO EVENT SHALL THE DEVELOPER(S), AUTHOR(S), OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING BUT NOT LIMITED TO PERSONAL INJURY, LOSS OF LIFE, PROPERTY DAMAGE, EQUIPMENT DAMAGE, OR INACCURACIES) ARISING OUT OF OR IN CONNECTION WITH THE USE, RELIANCE UPON, OR INABILITY TO USE THIS SOFTWARE.

---

## License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)**.

You are free to use, modify, and distribute this software for amateur radio purposes, provided that any derivative works are also open-source and released under the same GPLv3 license. See the `LICENSE` file for more details.
