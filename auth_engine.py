import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import Optional, Dict

import requests
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QSettings, Qt, pyqtSlot
from PyQt6.QtWidgets import QDialog, QVBoxLayout
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
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.profile = QWebEngineProfile.defaultProfile()
        self.page = InterceptPage(self.profile, self)
        self.page.code_received.connect(self._on_code_received_from_page)
        
        self.webview = QWebEngineView(self)
        self.webview.setPage(self.page)
        
        layout.addWidget(self.webview)
        
        self.webview.load(QUrl(auth_url))
        
    @pyqtSlot(str)
    def _on_code_received_from_page(self, auth_code: str):
        self.code_received.emit(auth_code)
        self.accept()

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
        
        self._code_verifier = ""

    def is_logged_in(self) -> bool:
        return bool(self._id_token)

    def get_username(self) -> str:
        if not self._id_token:
            return ""
        try:
            parts = self._id_token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                payload += '=' * (-len(payload) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
                return data.get("pota:callsign", data.get("pota:fullname", data.get("email", data.get("cognito:username", ""))))
        except Exception:
            pass
        return ""

    def start_login_flow(self, parent_widget=None):
        """Starts the OAuth login flow using an embedded web browser."""
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
        """Handles the code received from the browser and exchanges it for tokens."""
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
        
        try:
            resp = requests.post(f"{COGNITO_DOMAIN}/oauth2/token", data=data, headers=headers, timeout=10)
            resp.raise_for_status()
            tokens = resp.json()
            self._save_tokens(tokens)
            self.auth_state_changed.emit(True)
        except Exception as e:
            logger.error(f"Failed to exchange auth code for tokens: {e}")
            self.auth_state_changed.emit(False)

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
        """Clears stored tokens and emits logged out state."""
        self._id_token = ""
        self._refresh_token = ""
        self._access_token = ""
        self._token_expiry = 0
        
        self.settings.remove("id_token")
        self.settings.remove("refresh_token")
        self.settings.remove("access_token")
        self.settings.remove("token_expiry")
        
        # Also clear the browser profile so the user is actually signed out of Cognito
        profile = QWebEngineProfile.defaultProfile()
        profile.cookieStore().deleteAllCookies()
        
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
