import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl

app = QApplication(sys.argv)
web = QWebEngineView()
web.setUrl(QUrl("https://embed.windy.com/embed2.html?lat=38.3125&lon=-81.7083&zoom=6&level=surface&overlay=radar"))
web.show()
sys.exit(app.exec())
