#!/usr/bin/env bash
set -e

# Define directory variables
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Clean up previous builds to ensure fresh build
rm -rf dist build AppDir *.AppImage

# 1. Activate your python environment and install PyInstaller
echo "=== Installing PyInstaller in the virtual environment ==="
/home/kmcgrat/pyenv/bin/pip install pyinstaller

# 2. Run PyInstaller to bundle the python app into dist/pota-hunter/
echo "=== Building standalone folder with PyInstaller ==="
/home/kmcgrat/pyenv/bin/pyinstaller --noconfirm --clean --windowed --name pota-hunter main.py

# 3. Download appimagetool if it doesn't exist
echo "=== Fetching packaging tools ==="
mkdir -p build_tools
cd build_tools

if [ ! -f "appimagetool" ]; then
    echo "Downloading appimagetool..."
    curl -Lo appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi

cd ..

# 4. Make sure app icon is present
if [ ! -f "pota_hunter.png" ]; then
    echo "Error: pota_hunter.png icon not found in workspace root."
    exit 1
fi

# 5. Create manual AppDir structure
echo "=== Creating AppDir structure ==="
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

# Copy PyInstaller contents
cp -r dist/pota-hunter/* AppDir/usr/bin/

# Copy desktop and icon metadata files
cp pota_hunter.desktop AppDir/
cp pota_hunter.desktop AppDir/usr/share/applications/
cp pota_hunter.png AppDir/
cp pota_hunter.png AppDir/usr/share/icons/hicolor/256x256/apps/pota_hunter.png

# 6. Create custom AppRun script
echo "=== Creating AppRun entrypoint ==="
cat > AppDir/AppRun << 'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"

# Execute the bundled PyInstaller binary with arguments
exec "$HERE/usr/bin/pota-hunter" "$@"
EOF
chmod +x AppDir/AppRun

# 7. Package using appimagetool
echo "=== Packaging AppImage ==="
export ARCH=x86_64
export VERSION="26.8.7"


# Run appimagetool to create the final AppImage file
./build_tools/appimagetool AppDir POTA_Hunter-x86_64.AppImage

echo "=== Packaging Complete! ==="
echo "AppImage created successfully in: $DIR"
ls -lh POTA_Hunter-x86_64.AppImage

