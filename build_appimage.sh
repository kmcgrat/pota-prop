#!/usr/bin/env bash
set -e

# Define directory variables
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Clean up previous builds to ensure fresh build
rm -rf dist build AppDir *.AppImage

# Detect version dynamically from pota_prop.py
VERSION=$(grep -oP 'APP_VERSION = "\K[^"]+' pota_prop.py 2>/dev/null || echo "latest")
echo "=== Building POTA Prop v${VERSION} ==="

# 1. Resolve PyInstaller executable
if [ -f "/home/kmc/py_env/bin/pyinstaller" ]; then
    PYINSTALLER="/home/kmc/py_env/bin/pyinstaller"
elif [ -f "$DIR/.venv/bin/pyinstaller" ]; then
    PYINSTALLER="$DIR/.venv/bin/pyinstaller"
elif command -v pyinstaller &>/dev/null; then
    PYINSTALLER="pyinstaller"
else
    echo "Error: pyinstaller executable not found. Please activate your environment."
    exit 1
fi

echo "Using PyInstaller: $PYINSTALLER"

# 2. Exclude unused Qt6 and standard library modules to trim AppImage size
EXCLUDES="--exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtSql --exclude-module PyQt6.QtSensors --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtBluetooth --exclude-module PyQt6.QtNfc --exclude-module PyQt6.QtWebSockets --exclude-module PyQt6.QtPositioning --exclude-module PyQt6.QtTest --exclude-module PyQt6.QtDesigner --exclude-module PyQt6.QtHelp --exclude-module PyQt6.QtLocation --exclude-module PyQt6.QtQuickWidgets --exclude-module PyQt6.QtRemoteObjects --exclude-module PyQt6.QtSerialPort --exclude-module PyQt6.QtSvg --exclude-module PyQt6.QtSvgWidgets --exclude-module PyQt6.QtTextToSpeech --exclude-module PyQt6.QtXml --exclude-module tkinter --exclude-module unittest --exclude-module pdb --exclude-module pydoc"

# 3. Run PyInstaller to bundle the python app into dist/pota-prop/
echo "=== Building standalone directory with PyInstaller ==="
$PYINSTALLER --noconfirm --onedir --windowed --name "pota-prop" \
    --add-data "pota_prop.png:." \
    --add-data "map.html:." \
    $EXCLUDES main.py

# 4. Download appimagetool if it doesn't exist
echo "=== Fetching packaging tools ==="
mkdir -p build_tools
cd build_tools

if [ ! -f "appimagetool" ]; then
    echo "Downloading appimagetool..."
    curl -Lo appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage || \
    wget -O appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi

cd ..

# 5. Make sure app icon is present
if [ ! -f "pota_prop.png" ]; then
    echo "Error: pota_prop.png icon not found in workspace root."
    exit 1
fi

# 6. Create AppDir structure
echo "=== Creating AppDir structure ==="
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

# Copy PyInstaller contents
cp -r dist/pota-prop/* AppDir/usr/bin/

# Remove graphics/system libraries that conflict with host proprietary drivers (NVIDIA/AMD) to fix GLX crashes
find AppDir/usr/bin -name "libGL*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libEGL*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libGLES*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libglx*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libdrm*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libgbm*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libstdc++*" -delete 2>/dev/null || true
find AppDir/usr/bin -name "libgcc_s*" -delete 2>/dev/null || true

# Copy desktop and icon metadata files
cp pota_prop.desktop AppDir/
cp pota_prop.desktop AppDir/usr/share/applications/
cp pota_prop.png AppDir/
cp pota_prop.png AppDir/usr/share/icons/hicolor/256x256/apps/pota-prop.png
cp pota_prop.png AppDir/usr/share/icons/hicolor/256x256/apps/pota_prop.png

# 7. Create custom AppRun entrypoint script
echo "=== Creating AppRun entrypoint ==="
cat > AppDir/AppRun << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH}"
export QT_QPA_PLATFORM=xcb
exec "${HERE}/usr/bin/pota-prop" "$@"
EOF
chmod +x AppDir/AppRun

# 8. Package using appimagetool
echo "=== Packaging AppImage ==="
export ARCH=x86_64
export VERSION="$VERSION"

# Run appimagetool to create the final AppImage file
APPIMAGE_EXTRACT_AND_RUN=1 ./build_tools/appimagetool AppDir pota-prop-x86_64.AppImage

# Provide compatibility alias
cp pota-prop-x86_64.AppImage POTA_Hunter-x86_64.AppImage 2>/dev/null || true

echo "=== Packaging Complete! ==="
echo "AppImage created successfully in: $DIR"
ls -lh pota-prop-x86_64.AppImage
