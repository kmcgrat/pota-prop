import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl

def is_chromebook_crostini():
    import socket
    if os.path.exists('/proc/version'):
        try:
            with open('/proc/version', 'r') as f:
                content = f.read().lower()
                if 'cros-kernel' in content or 'chromium.org' in content:
                    return True
        except Exception:
            pass
    try:
        if socket.gethostname() == 'penguin':
            return True
    except Exception:
        pass
    return False

# Configure Chromium/WebEngine flags based on platform context
if "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ:
    if is_chromebook_crostini():
        # Chromebook Crostini GPU drivers (virgl) fail with dma_buf/compositor. 
        # We force Mesa to use software rendering to prevent dma_buf freezes, 
        # but keep WebGL/GPU flags enabled so Chromium can still render WebGL.
        os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-gpu-blocklist --enable-webgl"
    else:
        # Standard machines: bypass GPU blocklist to ensure hardware-accelerated WebGL/Windy Radar work
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-webgl"

app = QApplication(sys.argv)
web = QWebEngineView()
web.setUrl(QUrl("https://embed.windy.com/embed2.html?lat=38.3125&lon=-81.7083&zoom=6&level=surface&overlay=radar"))
web.show()
sys.exit(app.exec())
