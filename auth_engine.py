import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import Optional, Dict, Any

import requests
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QSettings, Qt, pyqtSlot
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

logger = logging.getLogger(__name__)

# POTA AWS Cognito Constants
COGNITO_DOMAIN = "https://parksontheair.auth.us-east-2.amazoncognito.com"
CLIENT_ID = "7hluqct0n2nckib7i7sd5753oa"
# Assuming pota.app is a registered redirect URI for this client ID
REDIRECT_URI = "https://pota.app/"

def generate_pkce_pair() -> tuple[str, str]:
    """Generates a random code_verifier and code_challenge for PKCE."""
    # Verifier must be between 43 and 128 characters
    code_verifier = secrets.token_urlsafe(64)
    # Challenge is base64url(sha256(verifier))
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    return code_verifier, code_challenge

_AUTH_PROFILE: Optional[QWebEngineProfile] = None

def get_auth_profile() -> QWebEngineProfile:
    """Returns a shared persistent QWebEngineProfile for POTA authentication."""
    global _AUTH_PROFILE
    if _AUTH_PROFILE is None:
        from PyQt6.QtCore import QStandardPaths
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        storage_path = os.path.join(app_data, "pota_auth_profile")
        os.makedirs(storage_path, exist_ok=True)

        _AUTH_PROFILE = QWebEngineProfile("pota_auth_profile")
        _AUTH_PROFILE.setPersistentStoragePath(storage_path)
        _AUTH_PROFILE.setCachePath(os.path.join(storage_path, "Cache"))
        _AUTH_PROFILE.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        _AUTH_PROFILE.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    return _AUTH_PROFILE


class InterceptPage(QWebEnginePage):
    code_received = pyqtSignal(str)
    
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        url_str = url.toString()
        if url_str.startswith(REDIRECT_URI):
            query = urllib.parse.urlparse(url_str).query
            params = urllib.parse.parse_qs(query)
            if 'code' in params:
                self.code_received.emit(params['code'][0])
                return False  # Block the navigation so POTA JS doesn't consume the code
            elif 'error' in params:
                logger.error(f"OAuth error received: {params['error']}")
                return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)

class AuthWebBrowserDialog(QDialog):
    """
    An embedded browser dialog that navigates to the Cognito login page
    and intercepts the redirect back to the REDIRECT_URI to extract the auth code.
    """
    code_received = pyqtSignal(str)

    def __init__(self, auth_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign In to POTA")
        self.resize(500, 650)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.profile = get_auth_profile()
        self.page = InterceptPage(self.profile, self)
        self.page.code_received.connect(self._on_code_received_from_page)
        
        self.webview = QWebEngineView(self)
        self.webview.setPage(self.page)
        
        layout.addWidget(self.webview, 1)
        
        # Privacy & cookie notice acknowledgment banner at the bottom
        self.cookie_banner = QWidget(self)
        self.cookie_banner.setObjectName("cookieBanner")
        self.cookie_banner.setFixedHeight(46)
        self.cookie_banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cookie_banner.setStyleSheet("""
            QWidget#cookieBanner {
                background-color: #161b22;
                border-top: 1px solid #30363d;
                min-height: 46px;
                max-height: 46px;
            }
            QLabel {
                color: #c9d1d9;
                font-size: 12px;
            }
            QPushButton {
                background-color: #238636;
                color: #ffffff;
                border: 1px solid #2ea043;
                border-radius: 4px;
                padding: 3px 14px;
                font-size: 12px;
                font-weight: bold;
                height: 26px;
                min-height: 26px;
                max-height: 26px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
            QPushButton:pressed {
                background-color: #1b4b27;
            }
        """)
        
        banner_layout = QHBoxLayout(self.cookie_banner)
        banner_layout.setContentsMargins(16, 8, 16, 8)
        banner_layout.setSpacing(12)
        
        lbl_notice = QLabel("Notice: Local session cookies are saved to keep you signed in on this device.", self.cookie_banner)
        banner_layout.addWidget(lbl_notice, 1)
        
        btn_ok = QPushButton("OK", self.cookie_banner)
        btn_ok.setFixedWidth(52)
        btn_ok.setFixedHeight(26)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.cookie_banner.hide)
        banner_layout.addWidget(btn_ok, 0)
        
        layout.addWidget(self.cookie_banner, 0)
        
        self.webview.load(QUrl(auth_url))
        
    @pyqtSlot(str)
    def _on_code_received_from_page(self, auth_code: str):
        self.code_received.emit(auth_code)
        self.accept()

    def closeEvent(self, event):
        if hasattr(self, 'webview') and self.webview:
            self.webview.stop()
        super().closeEvent(event)

class POTAAuthenticator(QObject):
    """
    Manages POTA authentication state, PKCE flow, and token refreshing.
    Emits signals when the authentication state changes.
    """
    auth_state_changed = pyqtSignal(bool)  # True if logged in, False if logged out

    def __init__(self):
        super().__init__()
        self.settings = QSettings("POTA", "HunterAuth")
        self._id_token = self.settings.value("id_token", "")
        self._refresh_token = self.settings.value("refresh_token", "")
        self._access_token = self.settings.value("access_token", "")
        self._token_expiry = self.settings.value("token_expiry", 0, type=float)
        self._callsign = self.settings.value("callsign", "")
        
        self._code_verifier = ""
        self.browser = None

    def is_logged_in(self) -> bool:
        return bool(self._id_token)

    def fetch_user_profile(self, id_token: Optional[str] = None) -> Dict[str, Any]:
        """Fetches the authenticated user profile from POTA API to extract operator callsign."""
        token = id_token or self.get_valid_token()
        if not token:
            return {}
        try:
            resp = requests.get(
                "https://api.pota.app/user/profile",
                headers={"Authorization": token, "Accept": "application/json"},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                callsign = data.get("callsign") or data.get("operator") or data.get("user") or ""
                if callsign:
                    self._callsign = str(callsign).strip().upper()
                    self.settings.setValue("callsign", self._callsign)
                return data
        except Exception as e:
            logger.debug(f"Failed to fetch POTA user profile: {e}")
        return {}

    def get_callsign(self) -> str:
        """Extracts the operator callsign from stored profile or ID token claims."""
        if self._callsign:
            return self._callsign
        if not self._id_token:
            return ""
        try:
            parts = self._id_token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                payload += '=' * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
                for key in ("custom:callsign", "pota:callsign", "preferred_username", "cognito:username", "name"):
                    val = data.get(key, "")
                    if val and "@" not in str(val):
                        self._callsign = str(val).strip().upper()
                        self.settings.setValue("callsign", self._callsign)
                        return self._callsign
        except Exception:
            pass
        return self._callsign or ""

    def get_username(self) -> str:
        call = self.get_callsign()
        if call:
            return call
        if not self._id_token:
            return ""
        try:
            parts = self._id_token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                payload += '=' * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
                return data.get("pota:fullname", data.get("email", data.get("cognito:username", "")))
        except Exception:
            pass
        return ""

    def start_login_flow(self, parent_widget=None):
        """Starts the OAuth login flow using an embedded web browser."""
        if self.browser is not None:
            try:
                self.browser.close()
                self.browser.deleteLater()
            except Exception:
                pass
            self.browser = None

        self._code_verifier, code_challenge = generate_pkce_pair()
        
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge
        }
        auth_url = f"{COGNITO_DOMAIN}/oauth2/authorize?{urllib.parse.urlencode(params)}"
        
        self.browser = AuthWebBrowserDialog(auth_url, parent=parent_widget)
        self.browser.code_received.connect(self._on_code_received)
        self.browser.show()

    def _on_code_received(self, auth_code: str):
        """Handles the code received from the browser and exchanges it for tokens asynchronously."""
        import threading
        
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": self._code_verifier
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        def exchange_worker():
            try:
                resp = requests.post(f"{COGNITO_DOMAIN}/oauth2/token", data=data, headers=headers, timeout=10)
                resp.raise_for_status()
                tokens = resp.json()
                self._save_tokens(tokens)
                # Fetch profile to extract callsign from POTA API
                self.fetch_user_profile(tokens.get("id_token"))
                self.auth_state_changed.emit(True)
            except Exception as e:
                logger.error(f"Failed to exchange auth code for tokens: {e}")
                self.auth_state_changed.emit(False)

        threading.Thread(target=exchange_worker, daemon=True).start()

    def _save_tokens(self, tokens: Dict):
        """Saves tokens and calculates expiry time."""
        self._id_token = tokens.get("id_token", "")
        self._access_token = tokens.get("access_token", "")
        # Refresh token is only returned in the initial code exchange
        if "refresh_token" in tokens:
            self._refresh_token = tokens.get("refresh_token", "")
            
        expires_in = tokens.get("expires_in", 3600)
        self._token_expiry = time.time() + expires_in - 300  # Refresh 5 minutes early
        
        self.settings.setValue("id_token", self._id_token)
        self.settings.setValue("refresh_token", self._refresh_token)
        self.settings.setValue("access_token", self._access_token)
        self.settings.setValue("token_expiry", self._token_expiry)

    def logout(self):
        """Clears stored tokens and emits logged out state while keeping device trust cookies."""
        self._id_token = ""
        self._refresh_token = ""
        self._access_token = ""
        self._token_expiry = 0
        self._callsign = ""
        
        self.settings.remove("id_token")
        self.settings.remove("refresh_token")
        self.settings.remove("access_token")
        self.settings.remove("token_expiry")
        self.settings.remove("callsign")
        
        if self.browser is not None:
            try:
                self.browser.close()
                self.browser.deleteLater()
            except Exception:
                pass
            self.browser = None
        
        self.auth_state_changed.emit(False)

    def get_valid_token(self) -> Optional[str]:
        """
        Returns a valid ID token. If the token is expired but a refresh token exists,
        it will attempt to refresh the token synchronously.
        Returns None if not logged in or refresh fails.
        """
        if time.time() < self._token_expiry and self._id_token:
            return self._id_token
            
        if not self._refresh_token:
            return None
            
        # Need to refresh
        data = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": self._refresh_token
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            resp = requests.post(f"{COGNITO_DOMAIN}/oauth2/token", data=data, headers=headers, timeout=10)
            resp.raise_for_status()
            tokens = resp.json()
            self._save_tokens(tokens)
            return self._id_token
        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            # If refresh fails (e.g., token revoked), log them out
            self.logout()
            return None
