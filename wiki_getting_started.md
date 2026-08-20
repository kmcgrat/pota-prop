# Getting Started with POTA Prop

Welcome to **POTA Prop**! This guide will help you get the application up and running on your system. 

## What is POTA Prop?

**POTA Prop** is a premium desktop GUI application designed for amateur radio operators participating in **Parks on the Air (POTA)**. It maps live pota.app activator spots and uses real-time physics modeling to predict your **QSO Success Probability (QSO Score)**.

Key features include:
* **Live POTA Spot Synchronization**: Asynchronously fetches active spots, highlighting NEW (unhunted) parks versus already-worked references.
* **HF/VHF Propagation & QSO Score Physics**: Models multi-layer ionospheric profiles (E, F1, F2), multi-hop ray tracing ($1E, 2E, 1F2, 2F2$, etc.), and skip-zone obliquity.
* **Comprehensive Mode Support**: Full SNR modeling and decoding thresholds for **CW, SSB, FT8, FT4, JS8, PSK (31/63/125), FM, AM, and Other Digital modes** (VarAC, VARA, Olivia, RTTY, etc.), taking into account sub-noise digital decoding.
* **Official POTA ISO Country Naming**: Integrates the complete UN ISO 3166-1/2 country database for accurate global park identification, clean table formatting (US/CA state abbreviations, clean country names), and rich tooltips.
* **NOAA SWPC D-RAP Absorption**: Real-time integration with NOAA SWPC D-Region Absorption Predictions model for accurate daytime HF attenuation.
* **Real-time Propagation Summary**: Synthesizes all live space weather (including NOAA SWPC 3-day forecast & 27-day solar cycle outlook), D-RAP absorption, aurora boundary dynamics, meteor showers, Blitzortung lightning QRN, global 3-day convective thunderstorm forecasts, seasonal lightning climatology, and live POTA spot distribution into an objective, technical Area Forecast Discussion (AFD) narrative.
* **Hybrid Interactive Propagation & Weather Map**: 
  * Displays global real-time 100W link budget heatmaps and propagation skip lines, with map-independent filters and decoupled opacity control.
  * **Live Doppler Weather Radar**: Automatically polls and updates RainViewer precipitation reflectivity sweeps every 5 minutes.
  * **Show Aurora Oval**: Renders NOAA SWPC OVATION model auroral boundaries with bold dark green core belts and dashed equatorward viewlines.
  * **Show Lightning Clusters**: Displays real-time Blitzortung thunderstorm cluster markers (`⚡` / `⚡➤` with directional motion vectors) and storm telemetry popups.
  * **Hybrid Architecture**: Uses native Qt6 `QWebEngineView` on standard Linux/Windows, and seamlessly serves via a secure, hardware-accelerated local HTTP map server on Chromebooks (ChromeOS / Crostini).
* **Blitzortung Live Lightning Noise (QRN)**: Integrates real-time Blitzortung WebSocket stroke telemetry and NOAA NWS alerts with storm cell trajectories and estimated Time of Arrival (TOA).
* **PSKReporter & RBN Integration**: Polls regional receiver nodes in real-time to empirically verify live RF openings.
* **ITU-R P.372-16 Receiver Band Noise Floor**: Models diurnal Day/Night atmospheric, galactic, and man-made noise curves across 11 bands (160m to 6m).
* **Open-Meteo Weather**: Integrates current weather observations and 12-hour hourly forecast cards directly inside the dashboard.
* **Flexible Startup Modes & Preferences**: Configure startup mode (Home QTH vs. Portable P2P Mode with automatic park grid resolution) under Preferences (`Ctrl+P`).

---

## Method 1: Using the Pre-compiled Executables (Windows & Linux Only)

For Windows and regular Linux users, using the pre-built executables is the fastest way to get started. You do not need to install Python or manage any dependencies. *(Note: macOS and Chromebook Crostini users **can** use Method 2 below).*

1. Go to the **[Releases](https://github.com/kmcgrat/pota-prop/releases)** page on GitHub.
2. Download the package for your operating system:
   * **Windows**: `pota-prop-windows-x64` (contains `pota-prop.exe`)
   * **Linux**: `pota-prop-linux-x86_64` (contains `POTA_Hunter-x86_64.AppImage`)

### Running on Windows
* Locate the downloaded `pota-prop.exe`.
* Double-click the file to launch the application. 
* *Note: The first time you run it, Windows Defender SmartScreen may show a warning because the executable is not signed. Click **More info** and then **Run anyway** to start the app.*

### Running on Linux (AppImage)
* Open your terminal and navigate to your downloads folder, or use your file manager.
* Make the AppImage executable. In the terminal, run:
  ```bash
  chmod +x POTA_Hunter-x86_64.AppImage
  ```
* Run it by double-clicking the file in your file manager or running it from the terminal:
  ```bash
  ./POTA_Hunter-x86_64.AppImage
  ```

---

## Method 2: Running Natively from Source Code (macOS, Chromebooks, & Power Users)

If you are on **macOS**, a **Chromebook**, or want to run natively from Python on **Windows/Linux**, you can run the source code directly.

### Prerequisites
Make sure you have **Python 3.10 or higher** installed on your system. You can verify your version by running:
```bash
python3 --version
```

### Step 1: Clone the Repository
Clone the repository to your local machine using Git:
```bash
git clone https://github.com/kmcgrat/pota-prop.git
cd pota-prop
```

### Step 2: Create a Virtual Environment (`venv`)
It is highly recommended to use a virtual environment to avoid conflicts with other Python packages on your system.

* **Windows**:
  ```powershell
  python -m venv .venv
  .venv\Scripts\activate
  ```
* **macOS / Linux / Chromebook**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### Step 3: Install Requirements
Install the required packages using `pip`:
```bash
pip install -r requirements.txt
```

### Step 4: Run the Application
Start the desktop application using the launcher script or Python:
* **macOS / Linux / Chromebook**:
  ```bash
  ./run.sh
  ```
  *(or run `python3 pota_prop.py` directly)*
* **Windows**:
  ```powershell
  python pota_prop.py
  ```

---

## Platform-Specific Setup Guides

### 🍏 macOS Setup
macOS users can run from source:
1. Install **Homebrew** (if you don't have it): https://brew.sh
2. Install Python 3:
   ```bash
   brew install python
   ```
3. Follow the **Method 2 (Source Code)** steps above.

### 💻 Chromebook Setup (ChromeOS Crostini)
POTA Prop runs smoothly on Chromebooks with hardware GPU acceleration via its hybrid local map server.

1. **Enable Linux**:
   * Open your Chromebook's **Settings**.
   * Go to **Advanced** > **Developers** and click **Turn On** next to "Linux development environment (Beta)".
   * Follow the on-screen instructions.
2. **Install System Dependencies**:
   Open your Linux terminal and install core packages:
   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip libegl1 libx11-xcb1 libgl1-mesa-glx libxcb-cursor0
   ```
3. **Follow the Method 2 (Source Code)** steps above to clone the repository, set up the virtual environment, and run `./run.sh`.
4. **Live Map on Chromebooks**: Clicking the **Live Propagation & Weather Map** button automatically launches a secure, local hardware-accelerated session in ChromeOS Chrome.

---

## First-Time Configuration & Operating Guide

Once the app is running:

1. **Configure Preferences (`Ctrl+P` or `File -> Preferences`)**:
   * **Operator Callsign**: Enter your callsign (e.g. `W8XYZ`). POTA Prop will automatically look up your grid locator.
   * **Grid Location**: Displays your active operating grid square. You can also click **Set Mobile/Temp** for automatic IP Geolocation.
   * **Startup Mode**:
     * Leave **Start in P2P Mode** unchecked to start at your home QTH.
     * Check **Start in P2P Mode** and enter a park reference (e.g. `US-1845`) if you primarily operate portable. The Grid Location will automatically update to that park's location.
   * **Local RBN/PSK Nodes**: Click **Auto-Find Nearest** to automatically identify the closest skimmer nodes to your QTH.

2. **Sync POTA Data**: 
   * Click **Sign In POTA.app** to authenticate your POTA profile in the embedded login window.
   * Click **Sync Log** (or **Sync POTA Data**) to automatically download and sync your hunted parks.

3. **Explore the Live Propagation & Weather Map**:
   * Click the **Live Map** button on the main toolbar, press **F4**, or select *View &rarr; Live Propagation & Weather Map*.
   * Filter bands and modes dynamically with live active park counts per band.
   * View the real-time 100W link budget heatmap, hover for exact probability percentages, and toggle dark map mode.
   * Inspect color-coded activator pins with `+` local verification badges and click popups with Path MUF status dots.
   * Toggle **RainViewer Global Radar** and **US NOAA NEXRAD Composite** with independent opacity sliders.
   * Toggle **Show Grayline** for real-time day/night solar terminator lines.
   * Toggle **Show Aurora Oval** for NOAA SWPC Northern & Southern auroral boundaries.
   * Toggle **Show Lightning Clusters** for real-time Blitzortung thunderstorm cells with ground speed and motion heading arrows.

---

## 🗺️ Interactive Live Propagation, Space Weather & Doppler Radar Map Guide

The **Live Map** provides a comprehensive, hardware-accelerated global visualization of your station's link budget, active activator pins, Doppler weather radar, space weather boundaries, and regional thunderstorm clusters.

### 1. Launching & Architecture
* **Quick Launch**: Click the green **Live Map** button on the top toolbar, press **F4**, or select `View -> Live Propagation & Weather Map (F4)`.
* **Standard Desktops (Linux / Windows)**: Runs natively inside an embedded Qt6 `QWebEngineView` with bidirectional IPC synchronization.
* **Chromebooks (ChromeOS Crostini) & Browser Fallback**: Automatically serves through a secure, lightweight local HTTP server (`map_server.py`) with tokenized authentication, launching directly in ChromeOS Chrome with full GPU hardware acceleration.

### 2. Floating Propagation Controls HUD
A collapsible HUD panel is anchored in the top-right corner of the map:
* **Collapse / Expand (`▼` / `▶`)**: Click the collapse button in the HUD title bar to minimize the controls to a slim header, freeing up viewing area across the globe.
* **Band Selector with Live Park Counts**: Select any band (160m through 70cm, or All). The dropdown dynamically displays active park counts in real time (e.g. `20m (48)`, `40m (32)`, `All Spots (142 Parks)`).
* **Mode Selector**: Choose between CW, SSB, FT8, FT4, JS8, PSK, FM, AM, or Other Digital.
* **Heatmap Opacity Slider**: Adjusts the transparency of the 100W propagation coverage heatmap (0.0 to 1.0) without dimming base geographic features, Grayline polylines, or weather overlays.
* **Dark Map Mode**: Toggles between high-contrast Carto Light and sleek Carto Dark basemap tiles.
* **Fullscreen View (`⛶` / F11 / Esc)**: Click the `⛶` button or press **F11** to toggle borderless fullscreen viewing on dedicated station monitors. Press **Esc** to exit.
* **Telemetry Update Status**: Displays the UTC timestamp of the latest propagation recalculation (e.g. `Last Updated: 14:30 UTC`) or `Updating... Standby...` during recalculation passes.

### 3. Real-Time 100W Propagation Heatmap
The engine models your station's 100W link budget across the entire globe at 1° latitude by 2° longitude Maidenhead sub-square resolution:
* **Green (≥99% / 100%)**: Exceptional propagation — robust signal levels well above decoding thresholds.
* **Yellow / Gold (50%–99%)**: Good / High probability — reliable skywave path within the optimal MUF window.
* **Orange (25%–50%)**: Marginal path — weak signals near the receiver noise floor.
* **Red (<25%)**: Poor / Closed — path closed due to skip-zone penetration or severe D-layer attenuation.
* **Interactive Hover Score**: Hover your mouse over any region or ocean to view the exact calculated percentage (`Propagation Score: XX%`) in the HUD footer.
* **Recalculation Cadence**: Recalculates on initial map open, instantly on band/mode filter changes, and automatically every 10 minutes in a non-blocking background thread (`MapPropagationWorker`).

### 4. Active Spot Pins & Click Popups
Every active activator is plotted at their park's exact latitude and longitude with hardware-rendered vector pins:
* **Two-Dimensional Visual Pin Status**:
  * **Interior Fill Color (QSO Score)**: Color-coded by predicted QSO score: **Green (≥99)**, **Yellow (≥75)**, **Orange (≥50)**, and **Red (<50)**.
  * **⚪ Crisp White Border Ring (`.spot-marker-new`)**: Marks **NEW (Unhunted)** parks.
  * **🔴 Crimson Red Border Ring (`.spot-marker-worked`)**: Marks **WORKED (Already Hunted)** parks in your log.
* **Local Verification `+` Badge**: Pins display a white `+` inside the circle if fellow operators in your call area or DXCC entity have confirmed hearing the station.
* **Activator QRP Power Modeling (⚡)**: Automatically parses case-insensitive QRP announcements (`5W`, `10W`, `KX2`, `IC-705`, `/QRP`, etc.) from self-respots and comments, adjusting received SNR against your real-time noise floor and lightning QRN.
* **HUD Legend Status Key**: Mini dot preview key at the bottom of the floating HUD (`⚪ New | 🔴 Worked | + Local`).
* **Interactive Popups**: Click any pin to inspect:
  * **Activator Callsign, Status & QRP**: Callsign (e.g. `W1AW/P`), `[NEW]` / `[WORKED]` badge, and `[⚡ QRP 5W]` tag.
  * **Park Reference & Name**: Official POTA reference code and park description.
  * **Operating Frequency (MHz) & Mode**
  * **Estimated QSO Score** (e.g. `Score: 92+`)
  * **Path MUF & Color Dot**: Maximum Usable Frequency in MHz with status dot:
    * 🟢 **Green (≥28 MHz)**: Upper HF wide open up to 10m.
    * 🟡 **Yellow (18–28 MHz)**: Mid-HF open (15m–20m).
    * 🔴 **Red (<18 MHz)**: Upper HF closed, lower HF only.

### 5. Dual Live Doppler Weather Radar Overlays
* **RainViewer Global Radar**: Global composite precipitation reflectivity layer updated every 10 minutes via the RainViewer API, featuring an independent opacity slider.
* **US NOAA NEXRAD Composite**: High-resolution continental US base reflectivity (N0Q) composite radar tiles from IEM / NOAA with an independent opacity slider.

### 6. Day/Night Grayline & Solar Terminator
Toggle **Show Grayline** to display real-time twilight boundaries:
* **Solid Black Line**: 90° solar zenith (sunrise/sunset terminator line).
* **Dashed Black Line**: 96° solar zenith (civil twilight boundary).
* **Dashed Gray Line**: 84° solar zenith (golden hour daylight boundary).

### 7. NOAA SWPC Aurora Oval (OVATION Model)
Toggle **Show Aurora Oval** to display live Northern (Borealis) and Southern (Australis) auroral boundaries:
* **Core Auroral Belts**: Bold dark green polylines representing primary auroral electrojet activity.
* **Equatorward Viewlines**: Dark gray dashed polylines showing the southernmost/northernmost boundaries where aurora is visible on the horizon.

### 8. Blitzortung.org Lightning Clusters & Storm Motion Vectors
Toggle **Show Lightning Clusters** to track regional convective threats within 750 miles:
* **Stationary Cells (`⚡`)**: Glowing yellow marker in a pulsing circular boundary.
* **Moving Storm Cells (`⚡➤`)**: Directional arrow rotated along the storm cell's exact ground motion vector.
* **Cluster Popups**: Click any storm marker to inspect event type (Severe Thunderstorm, Tornado, Marine Warning, Flash Flood), estimated stroke count, ground speed (mph), cardinal heading, and active NOAA NWS warning headlines.

---

## ⌨️ Keyboard Shortcuts Reference

| Key Shortcut | Action | Context |
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

## Author & Project Credits

* **Designed & Tested by**: Kevin McGrath (**W7KMC**) for the Amateur Radio and Parks on the Air (POTA) community.

## Data Sources & Credits

POTA Prop heavily relies on the incredible work of the following open platforms and data sources. Please consider supporting them or contributing to their crowdsourced networks:

* **Parks on the Air (POTA)** - The core spot stream and official park database. ([parksontheair.com](https://parksontheair.com))
* **Blitzortung.org** - Real-time crowd-sourced lightning telemetry. ([blitzortung.org](https://www.blitzortung.org))
* **RainViewer** - Live Doppler weather radar API. ([rainviewer.com](https://www.rainviewer.com))
* **IEM / NOAA Nexrad** - Live US weather radar tiles. ([mesonet.agron.iastate.edu](https://mesonet.agron.iastate.edu/))
* **PSKReporter & RBN** - Live reverse beacon network spotting. ([pskreporter.info](https://pskreporter.info))
* **Open-Meteo** - Excellent free, open-source weather API. ([open-meteo.com](https://open-meteo.com))
* **NOAA SWPC** - Space weather data (SFI, K-index, A-index), D-RAP Absorption & OVATION Aurora Oval models. ([swpc.noaa.gov](https://www.swpc.noaa.gov))
* **Carto & OpenStreetMap** - Map rendering and basemap tiles. ([openstreetmap.org](https://www.openstreetmap.org))

