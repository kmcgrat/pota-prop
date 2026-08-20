# POTA Prop

A desktop GUI application built in Python and PyQt6 for amateur radio operators participating in **Parks on the Air (POTA)**.

It compares your hunted parks export against active spots on [pota.app](https://pota.app), highlighting which active activators represent **NEW (unhunted)** parks versus parks you have already worked, and calculates an estimated **QSO Success Probability (Score)** based on ionospheric propagation modeling, ray tracing, skip-zone physics, live space weather, and regional lightning noise (QRN).

---

## Key Features

- **Live POTA Spot Synchronization**: Asynchronously fetches active spots from `https://api.pota.app/spot/activator` with configurable auto-refresh intervals (Manual, 30s, 1m, 2m, 5m).
- **HF/VHF Propagation & QSO Score Modeling**:
  - **Multi-Layer Ionospheric Profile (E, F1, F2)**: Computes Chapman solar-zenith electron density for E/F1 layers and diurnal variation for the F2 layer ($foE, hmE, foF1, hmF1, foF2, hmF2, ymF2$).
  - **Multi-Hop Ray Tracing ($1E, 2E, 1F2, 2F2, 3F2, 4F2$)**: Calculates takeoff launch elevation angles ($\Delta$) and ionospheric incidence angles ($\phi_{\text{inc}}$) across Great-Circle paths to identify the dominant ray path mode.
  - **Skip-Zone Calculations**: Evaluates oblique critical frequency ($f \le foF2 \sec \phi_{\text{inc}}$). If an operating frequency exceeds the oblique MUF on short skip or nighttime paths, the path is flagged as closed.
  - **Comprehensive Mode Support & Sub-Noise Decoding**: Full bandwidth and SNR threshold modeling for **CW (-10 dB), SSB (+4 dB), FT8 (-21 dB), FT4 (-17 dB), JS8 (-21 dB), PSK (-8 dB), FM (+10 dB), AM (+16 dB), and Other Digital (-10 dB)** (VarAC, VARA, Olivia, RTTY, etc.).
  - **Official POTA ISO Country Naming & Location Formatting**: Integrates the complete UN ISO 3166-1/2 entity database across 249 global POTA programs, providing clean table display (US/CA state abbreviations, clean country names) and detailed mouseover tooltips.
  - **NOAA SWPC D-RAP Absorption Model**: Real-time integration of NOAA D-Region Absorption Predictions to model daytime solar X-ray attenuation.
  - **Global DXCC & Region Mapping**: Automatically resolves international DXCC entities (US, Canada, Europe, Oceania, etc.) using local prefix and geolocation context for realistic global verification bonuses.
  - **Regional Lightning & Convective Threat Engine**: Hybrid architecture combining instant **NOAA NWS Convective Alerts** (Severe Thunderstorm, Tornado, Marine, Flash Flood warnings with active popup alerts) with real-time **Blitzortung.org** live WebSocket stroke telemetry across a 750-mile radius. Features **Storm Cell Trajectory Tracking** deriving ground speed (mph), cardinal movement direction, and **Time of Arrival (TOA in minutes)** estimates for approaching storms. Features a 1-to-10 threat scale, station safety advisories (Level 9/10 feedline disconnect alerts), and frequency-dependent noise surge ($\Delta F_{\text{QRN}}$) modeling.
  - **Open-Meteo Local Weather & 12-Hour Hourly Forecast**: Top dashboard card displaying current temperature and weather condition icon (`72°F ⛅`). Mouseover popup opens a 12-hour hourly forecast table with **Time (UTC)** in 24-hour format, temperature (°F), weather condition icons/descriptions, wind vectors, and Open-Meteo attribution.
  - **Receiver Band Noise Floor Matrix (ITU-R P.372-16)**: Full 11-band noise floor engine (160m to 6m) modeling diurnal day/night atmospheric noise curves, cosmic/galactic background, man-made baselines, and live Blitzortung lightning QRN surges with standard IARU S-meter calibration ($S9 = -73\text{ dBm}$, $6\text{ dB/S-unit}$). Accessible via top dashboard stat card or **F6** hotkey.
  - **Station Link Budget & SNR Estimation**: Incorporates transmitter power (Watts to dBW), antenna radiation patterns (Dipole, End-Fed, Vertical, Loop, Random Wire, 3-Element Beam), free-space path loss ($L_{\text{bf}}$), ionospheric absorption ($L_a$) with geomagnetic gyrofrequency ($f_H = 1.4\text{ MHz}$), and ground reflection losses ($L_g$).
  - **Live Space Weather & Meteor Telemetry**: Background worker pulls 10.7cm Solar Flux Index (SFI), planetary K-index, planetary A-index, and GOES Satellite 0.1–0.8nm X-ray flux from NOAA SWPC. Also actively scrapes the **International Meteor Organization (IMO)** for live Meteor Shower activity (ZHR and shower peak data) to model 6m and 10m Sporadic-E enhancements.
  - **Automated QRT Detection & Empirical Overrides**: Adjusts QSO Score when spot comments indicate an activator is QRT (off the air). Integrates live network telemetry to override mathematical skip-zones:
    - **Live PSKReporter & RBN Intelligence Array**: Continuously polls a configurable comma-separated list of regional proxy receiver nodes (including live-scraped active RBN nodes within 200 miles) in a round-robin background thread to map live RF propagation across your region.
    - **Targeted Activator Sweeps**: Dynamically sweeps active digital POTA activators every 60 seconds to verify if regional spotters are successfully decoding them.
    - **Mode Penalty Logic**: Evaluates the Signal-to-Noise Ratio (SNR) of live FT8/FT4 decodes to estimate cross-mode viability. Exceptionally strong digital decodes (e.g. >= 0dB) provide massive empirical boosts (+15 points) for SSB targets, while weak decodes are scaled appropriately for CW or ignored for SSB to maintain realistic expectations.
    - **Grayline Enhancement**: Applies path adjustments when either endpoint or the path midpoint aligns with the solar terminator.
    - VHF/UHF Line-of-Sight & 6m Es Modeling: Bounds 2m/70cm to tropospheric line-of-sight range (~150 km max) and detects summer Sporadic-E skip paths for 6m.
- **Real-time Propagation Summary**:
  - **Comprehensive Narrative Dispatch**: Synthesizes all real-time space weather (SFI, SSN, Kp, solar wind), D-RAP solar flare absorption, NOAA SWPC auroral oval boundaries, meteor shower scatter bursts, Blitzortung lightning QRN, local weather, and active POTA spot distributions into an objective, technical Area Forecast Discussion (AFD) narrative.
  - **3-Day Space Weather Forecast & 27-Day Outlook**: Features NOAA SWPC numerical and narrative projections for 10.7cm Solar Flux, Planetary A-Index ($A_p$), peak Kp storm scales ($G0$–$G5$), M/X-class flare probabilities, and 27-day solar cycle peak DX windows.
  - **Global 3-Day Thunderstorm Outlook & Seasonal QRN Climatology**: Features global numerical convective modeling (Precipitation %, Thunderstorm probability %, CAPE in $\text{J/kg}$, and static crash severity) and NASA LIS/OTD seasonal lightning transitions.
  - Accessible directly via the **"Propagation Summary"** button on the bottom action bar, with one-click clipboard copying.
- **Hybrid Live Propagation & Weather Map**:
  - **100W Link Budget Heatmap**: Mathematically models real-time 100W link budget and QSO probabilities globally across the earth's surface using 1° latitude × 2° longitude Maidenhead sub-square resolution.
  - **4-Stage Color Scale & Hover Diagnostics**: Renders smooth gradients (Green ≥99%, Yellow 50–99%, Orange 25–50%, Red <25%) with real-time hover percentage readouts (`Propagation Score: XX%`).
  - **Floating HUD & Live Park Counts**: Collapsible top-right HUD panel (`▼`/`▶`) with independent Band and Mode filters displaying live active park counts (e.g. `20m (48)`), Dark Map mode toggle, and decoupled Heatmap Opacity slider (0.0 to 1.0) on an isolated layer (`heatmapPane`).
  - **Active Spot Pins & Path MUF Popups**: Plots active park activators color-coded by QSO score with white `+` local verification badges. Click popups display callsign, park reference/name, frequency, mode, score, and Path MUF (MHz) with color-coded dot status (🟢 ≥28 MHz, 🟡 18–28 MHz, 🔴 <18 MHz).
  - **Dual Doppler Weather Radar**: Integrated **RainViewer Global Radar** (10-minute API refresh) and **US NOAA NEXRAD Composite** (N0Q) tile layers with independent opacity sliders.
  - **Show Aurora Oval**: Integrates the NOAA SWPC OVATION model to render real-time Northern (Aurora Borealis) and Southern (Aurora Australis) auroral boundaries with bold dark green core belts and dashed equatorward viewlines (15-minute background cycle).
  - **Show Grayline**: Real-time solar terminator lines (90° sunset/sunrise line, 96° civil twilight boundary, 84° golden hour transition) with seamless global coordinate wrapping.
  - **Show Lightning Clusters**: Live Blitzortung thunderstorm cluster markers (`⚡` for stationary, `⚡➤` with directional motion vectors) displaying real-time cluster strike counts, storm ground speed (mph), movement heading, and NWS convective alert headlines.
  - **Hybrid Architecture**: Uses native Qt6 `QWebEngineView` on standard Linux and Windows desktops, and automatically runs a lightweight, secure local HTTP server (`map_server.py`) on Chromebooks (ChromeOS / Crostini) to render in ChromeOS Chrome with full hardware GPU acceleration.
  - **Keyboard Shortcuts & Fullscreen**: Dedicated toolbar button, `View -> Live Propagation & Weather Map` (`F4`), and native borderless Fullscreen capability (**F11** / **Esc** / `⛶`).
  - **Background Recalculation Lifecycle**: Recalculates upon initial launch, immediately on band/mode filter changes, and automatically on a strict 10-minute cycle via `MapPropagationWorker`.
- **Preferences & Startup Modes (`Ctrl+P`)**:
  - **Startup Mode Selection**: Set your preferred startup mode—**At Home** (using your callsign's home QTH) or **Start in P2P Mode**.
  - **P2P Field Park & Auto-Grid**: When operating portable, enter your field park reference (e.g. `US-1845`), and POTA Prop automatically looks up and sets your **Grid Location** to that park.
  - **Grid Location & Mobile/Temp Locator**: Displays your operating grid with a built-in **Set Mobile/Temp** button for automatic IP geolocation.
  - **Local RBN/PSK Nodes**: Quick auto-detection of nearest skimmer nodes within 200 miles.
- **Interactive Multi-Filter Controls**:
  - **Status Filter**: View *All*, *New*, *Hunted*, *Worked*, or *P2P*.
  - **QSO Score Filter**: Filter by *All (0+)*, *>= 25 (Possible)*, *>= 50 (Good)*, *>= 75 (High)*, or *>= 99 (Exceptional)*.
  - **Band Filter**: Filter by 160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 2m, 70cm, etc.
  - **Mode Filter**: Filter by CW, SSB, FT8, FT4, JS8, PSK, FM, AM, Other Digital.
  - **Instant Search**: Real-time search across Park ID, Park Name, Activator Callsign, Location/State, Grid, or Spotter Comments.
- **Summary Metric Cards**: Live counters for Unhunted Spots, Hunted Spots, Total Spots, Unique Active Parks, Total Parks in Log, Live NOAA Space Weather (SFI / K-Index with rich 3-day forecast breakdown tooltip), Regional Lightning Activity (1–10 Threat Scale), and Receiver Band Noise Floor (S-units).
- **Interactive Table & Resizable Columns**:
  - **13 Detailed Columns**: Status, `Score`, Activator, Frequency, Time, Park ID, Park Name, Location/State, Band, Mode, Distance & Bearing, Grid, Comments.
  - **Local Verification (`+` Symbol)**: Scores featuring a `+` (e.g. `85+`) indicate local spotter verification confirming nearby spotters in your region hear the signal.
  - **Interactive Diagnostics**: Hover over any `Score` badge or table row to see full path diagnostics (Ray Mode, Launch Angle, Path Loss, Predicted SNR, MUF, Lightning QRN Surge, Space Weather, and Empirical Network Data).
  - **Adjustable Column Widths**: Drag any column header boundary to resize columns.
  - **Auto-Fit & Reset**: Right-click any column header to access `Auto-fit All Column Widths` or `Reset Column Widths to Default`.
  - **Persistent Layout**: Custom column widths, window geometry, and home grid are automatically saved and restored across sessions.
  - **FIFO Status Message Queue**: Background telemetry (POTA spots, PSK fetches, Weather updates) elegantly feed into a localized status queue, displaying non-blocking 5-second rotating updates on the bottom status bar without overwhelming the user.
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
   - Once authenticated, click **Sync POTA Data** (or **Sync Log**). POTA Prop will automatically connect to the POTA API, download your entire historical hunted log, and integrate it instantly.
2. **Configure Your Station & Preferences (`Ctrl+P`)**:
   - Enter your **Operator Callsign** and **Grid Location** (e.g. `EM98dh`).
   - Select your preferred **Startup Mode** (At Home vs. P2P Mode).
   - Select your transmitter power (5W, 100W, 500W, 1500W) and antenna preset (Dipole, Vertical, Beam, etc.) on the main window to tailor the link budget.
3. **Explore the Live Propagation & Weather Map**:
   - Click the **Live Map** button on the main toolbar, press **F4**, or select `View -> Live Propagation & Weather Map`.
   - Filter bands and modes with live active park counts per band.
   - Inspect color-coded activator pins, `+` local verification badges, and click popups with Path MUF status dot indicators.
   - Toggle RainViewer Global Radar and US NOAA NEXRAD Composite layers with independent opacity sliders.
   - Toggle real-time Day/Night Grayline, NOAA SWPC Aurora Ovals, and Blitzortung lightning clusters with storm motion vectors.
4. **Marking Worked Parks Off Your List**:
   - Made a contact with an active park? Click the **Status** drop-down menu in the table row and select **Mark [WORKED]** (or right-click the row and select *Toggle Worked Status*).
   - The row immediately turns green, and your counters update. Manually worked parks are saved persistently across sessions!

---

## 🗺️ Live Propagation & Weather Map Guide

The **Live Map** provides a real-time, GPU-accelerated global visualization of your station's 100W link budget, active activator pins, Doppler weather radar, space weather boundaries, and regional thunderstorm clusters:

* **Floating Propagation Controls HUD**: Collapsible (`▼`/`▶`) top-right panel for configuring Band and Mode filters (with live active park counts), Heatmap Opacity slider (0.0–1.0 on dedicated `heatmapPane`), Dark Map Mode basemap toggle, and borderless Fullscreen viewing (**F11** / **Esc** / `⛶`).
* **100W Link Budget Heatmap**: Evaluates global QSO probability at 1° latitude × 2° longitude Maidenhead sub-square resolution with a 4-stage color scale: **Green (≥99%)**, **Yellow/Gold (50%–99%)**, **Orange (25%–50%)**, and **Red (<25%)**. Hover anywhere to view the exact predicted percentage (`Propagation Score: XX%`).
* **Active Spot Pins & Click Popups**: Plots active park activators with two-dimensional vector pin styling: interior fill colors for predicted QSO score (<span style="color:#2ea043">Green ≥99</span>, <span style="color:#d29922">Yellow ≥75</span>, <span style="color:#f78166">Orange ≥50</span>, <span style="color:#da3633">Red <50</span>), **⚪ Crisp White Border Rings** for NEW (unhunted) parks, and **🔴 Crimson Red Border Rings** for WORKED (already hunted) parks. Pins display a white `+` for local area verification. Popups show callsign, `[NEW]`/`[WORKED]` status, gold `[⚡ QRP 5W]` tags (automatically modeling activator low power), frequency, mode, score, and Path MUF (MHz) with status dots (🟢 ≥28 MHz, 🟡 18–28 MHz, 🔴 <18 MHz).
* **Dual Doppler Weather Radar**: Integrated **RainViewer Global Radar** (10-minute API refresh) and **US NOAA NEXRAD Composite** (N0Q) tile layers with dedicated opacity sliders.
* **Solar Terminator & Space Weather**: Real-time Day/Night Grayline (90°/96°/84° solar zenith angles) and NOAA SWPC OVATION Aurora Ovals (core green belts and dashed equatorward viewlines).
* **Blitzortung Lightning Clusters & Ground Motion Vectors**: Real-time `⚡` (stationary) and `⚡➤` (moving) storm cluster markers with directional motion heading arrows, ground speed (mph), strike totals, and active NWS warning headlines.
* **Platform Architecture**: Native Qt6 WebEngine on Linux/Windows, and automated hardware-accelerated local HTTP server (`map_server.py`) for Chromebooks (ChromeOS Crostini).

---

## ⌨️ Keyboard Shortcuts Reference

| Shortcut | Action | Context |
| :--- | :--- | :--- |
| **F1** | Open About POTA Prop dialog | Main Application |
| **F2 / Ctrl+H** | Open User Guide & Documentation | Main Application |
| **F4** | Open Live Propagation, Space Weather & Doppler Radar Map | Main Application |
| **F5** | Trigger immediate manual spot & weather refresh | Main Application |
| **F6** | Open Receiver Band Noise Floor Matrix dialog (ITU-R P.372) | Main Application |
| **F11** | Toggle Fullscreen Mode | Live Map Window |
| **Esc** | Exit Fullscreen Mode | Live Map Window |
| **Ctrl+P** | Open Preferences Manager | Main Application |
| **Ctrl+O** | Reload / Browse Hunter Log CSV | Main Application |
| **Ctrl+S** | Export filtered table view to CSV | Main Application |
| **Ctrl+Q** | Exit Application | Main Application |

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
python3 pota_prop.py
```

---

## Dependencies

- Python 3.10+
- `PyQt6`
- `PyQt6-WebEngine` (for native desktop map embedding on Linux/Windows)
- `requests`

Installed automatically in the Python environment. To install in a separate environment:
```bash
pip install -r requirements.txt
```

---

## Running Automated Tests

Run the full automated test suite:
```bash
python3 -m unittest test_web.py test_pota_prop.py
```

---

## Author & Acknowledgements

- **Designed & Tested by:** Kevin McGrath (**W7KMC**) for the Amateur Radio and Parks on the Air (POTA) community.
- **Data & Service Acknowledgements:**
  - **Parks on the Air (POTA)** - The core spot stream and official park database ([parksontheair.com](https://parksontheair.com))
  - **Blitzortung.org** - Real-time crowd-sourced lightning telemetry ([blitzortung.org](https://www.blitzortung.org))
  - **[PSKReporter.info](https://pskreporter.info)** & **[Reverse Beacon Network (RBN)](https://reversebeacon.net)**: For real-time crowdsourced RF reception and empirical propagation verification.
  - **[Open-Meteo](https://open-meteo.com)**: For free, high-resolution global weather forecasts without API key restrictions.
  - **[NOAA Space Weather Prediction Center (SWPC)](https://www.swpc.noaa.gov)**: For live solar flux, geomagnetic index, D-RAP absorption, and OVATION Aurora model data.
  - **[International Meteor Organization (IMO)](https://www.imo.net)**: For meteor shower calendar and real-time flux activity.
  - **[RainViewer](https://www.rainviewer.com)** & **[IEM / NOAA Nexrad](https://mesonet.agron.iastate.edu/)**: For Doppler weather radar tile layers.
  - **Carto & OpenStreetMap** - Map rendering and basemap tiles ([openstreetmap.org](https://openstreetmap.org))

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
