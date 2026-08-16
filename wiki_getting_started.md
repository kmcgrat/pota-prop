# Getting Started with POTA Prop

Welcome to **POTA Prop**! This guide will help you get the application up and running on your system. 

## What is POTA Prop?

**POTA Prop** is a premium desktop GUI application designed for amateur radio operators participating in **Parks on the Air (POTA)**. It maps live pota.app activator spots and uses real-time physics modeling to predict your **QSO Success Probability (QSO Score)**.

Key features include:
* **Live POTA Spot Synchronization**: Asynchronously fetches active spots, highlighting NEW (unhunted) parks versus already-worked references.
* **HF/VHF Propagation & QSO Score Physics**: Models multi-layer ionospheric profiles (E, F1, F2), multi-hop ray tracing ($1E, 2E, 1F2, 2F2$, etc.), and skip-zone obliquity.
* **Blitzortung Live Lightning Noise (QRN)**: Integrates real-time Blitzortung WebSocket stroke telemetry and NOAA NWS alerts with storm cell trajectories and estimated Time of Arrival (TOA).
* **PSKReporter & RBN Integration**: Polls regional receiver nodes in real-time to empirically verify live RF openings.
* **ITU-R P.372-16 Receiver Band Noise Floor**: Models diurnal Day/Night atmospheric, galactic, and man-made noise curves across 11 bands (160m to 6m).
* **Global Interactive Heatmap**: Displays your station's real-time 100W link budget and propagation path diagrams globally using Maidenhead grid coordinates.
* **Open-Meteo Weather**: Integrates current weather forecasts and 12-hour hourly forecast cards directly inside the dashboard.

---

## Method 1: Using the Pre-compiled Executables (Easiest)

For most users, using the pre-built executables is the fastest way to get started. You do not need to install Python or manage any dependencies.

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

## Method 2: Running Natively from Source Code (Power Users)

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
macOS users must run from source since pre-compiled macOS binaries are not currently generated.
1. Install **Homebrew** (if you don't have it): https://brew.sh
2. Install Python 3:
   ```bash
   brew install python
   ```
3. Follow the **Method 2 (Source Code)** steps above.

### 💻 Chromebook Setup
You can run POTA Prop on a Chromebook using the built-in **Linux Development Environment (Crostini)**.

1. **Enable Linux**:
   * Open your Chromebook's **Settings**.
   * Go to **Advanced** > **Developers** and click **Turn On** next to "Linux development environment (Beta)".
   * Follow the on-screen instructions (the default disk size is usually sufficient).
2. **Install System Dependencies**:
   PyQt6 requires underlying graphics libraries. Open your Linux terminal and install them:
   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip libegl1 libx11-xcb1 libgl1-mesa-glx libxcb-cursor0
   ```
3. **Follow the Method 2 (Source Code)** steps above to clone the repository, set up the virtual environment, and run the app.

---

## First-Time Configuration inside POTA Prop

Once the app is running:
1. **Configure your Station Info**: Enter your **My Call** and **Home Grid** (e.g. `EM98dh`) in the top left card.
2. **Sync POTA Data**: 
   * Click **Sign In POTA.app** to authenticate your POTA profile.
   * Click **Sync POTA Data** to automatically sync your hunted log.
3. **Enjoy Spotting!** The app will immediately calculate propagation scores to active POTA spots.
