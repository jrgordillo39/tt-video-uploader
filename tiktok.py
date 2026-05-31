import os
import json
import time
import logging
import httpx
import asyncio
import hashlib
import secrets
import base64
from pathlib import Path
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

TOKENS_FILE = "tiktok_tokens.json"

class TikTokAccount:
    """Represents a single authenticated TikTok account."""

    def __init__(self, alias: str, token_data: dict):
        self.alias = alias
        self.token_data = token_data

    @property
    def username(self) -> str:
        return self.token_data.get("username", self.alias)

    def is_authenticated(self) -> bool:
        if not self.token_data.get("access_token"):
            return False
        return time.time() < self.token_data.get("expires_at", 0)


class TikTokUploader:
    """
    Handles TikTok OAuth2 and video uploads for multiple accounts.
    Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
    """

    AUTH_URL      = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL     = "https://open.tiktokapis.com/v2/oauth/token/"
    USERINFO_URL  = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url"
    UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    QUERY_POST_URL  = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self):
        self.client_key    = os.getenv("TIKTOK_CLIENT_KEY")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
        self.redirect_uri  = os.getenv("TIKTOK_REDIRECT_URI", "https://localhost/callback")

        # { alias -> token_data_dict }
        self._accounts: dict[str, dict] = self._load_all()

        # alias of the currently selected account (per-session)
        self._selected: str | None = None

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load_all(self) -> dict:
        if Path(TOKENS_FILE).exists():
            with open(TOKENS_FILE) as f:
                return json.load(f)
        return {}

    def _save_all(self):
        with open(TOKENS_FILE, "w") as f:
            json.dump(self._accounts, f, indent=2)

    # ─── Account Management ───────────────────────────────────────────────────

    def list_accounts(self) -> list[TikTokAccount]:
        return [TikTokAccount(alias, data) for alias, data in self._accounts.items()]

    def get_account(self, alias: str) -> TikTokAccount | None:
        data = self._accounts.get(alias)
        return TikTokAccount(alias, data) if data else None

    def remove_account(self, alias: str) -> bool:
        if alias in self._accounts:
            del self._accounts[alias]
            self._save_all()
            if self._selected == alias:
                self._selected = None
            return True
        return False

    def select_account(self, alias: str) -> bool:
        if alias in self._accounts:
            self._selected = alias
            return True
        return False

    @property
    def selected_account(self) -> TikTokAccount | None:
        if self._selected and self._selected in self._accounts:
            return TikTokAccount(self._selected, self._accounts[self._selected])
        # Auto-select if only one account
        if len(self._accounts) == 1:
            alias = next(iter(self._accounts))
            return TikTokAccount(alias, self._accounts[alias])
        return None

    # ─── PKCE Helpers ─────────────────────────────────────────────────────────

    def _generate_pkce(self) -> tuple[str, str]:
        """Generate a PKCE code_verifier and its SHA256 code_challenge."""
        code_verifier  = secrets.token_urlsafe(64)
        digest         = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return code_verifier, code_challenge

    # ─── OAuth Flow ───────────────────────────────────────────────────────────

    def get_auth_url(self, alias: str) -> str:
        """Generate OAuth URL with PKCE. Stores verifier for later use."""
        code_verifier, code_challenge = self._generate_pkce()

        # Store verifier keyed by alias so exchange_code can retrieve it
        if not hasattr(self, "_pkce_verifiers"):
            self._pkce_verifiers = {}
        self._pkce_verifiers[alias] = code_verifier

        params = {
            "client_key":            self.client_key,
            "scope":                 "user.info.basic,video.publish,video.upload",
            "response_type":         "code",
            "redirect_uri":          self.redirect_uri,
            "state":                 f"tgbot_{alias}",
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, alias: str) -> bool:
        """Exchange OAuth code for access token and save under alias."""
        # Retrieve PKCE verifier generated during get_auth_url
        verifiers     = getattr(self, "_pkce_verifiers", {})
        code_verifier = verifiers.pop(alias, None)

        payload = {
            "client_key":    self.client_key,
            "client_secret": self.client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  self.redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        resp = httpx.post(self.TOKEN_URL, data=payload)

        if resp.status_code != 200 or "access_token" not in resp.json():
            logger.error(f"Code exchange failed: {resp.text}")
            return False

        data = resp.json()
        data["expires_at"] = time.time() + data.get("expires_in", 86400)
        data["alias"] = alias

        # Try to fetch TikTok display name
        display_name = self._fetch_display_name(data["access_token"])
        if display_name:
            data["username"] = display_name

        self._accounts[alias] = data
        self._save_all()
        logger.info(f"Account '{alias}' authenticated.")
        return True

    def _fetch_display_name(self, access_token: str) -> str | None:
        try:
            resp = httpx.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("user", {}).get("display_name")
        except Exception:
            pass
        return None

    # ─── Token Refresh ────────────────────────────────────────────────────────

    def _refresh_account(self, alias: str) -> bool:
        data = self._accounts.get(alias, {})
        if not data:
            return False

        # Still valid
        if time.time() < data.get("expires_at", 0):
            return True

        refresh_token = data.get("refresh_token")
        if not refresh_token:
            return False

        logger.info(f"Refreshing token for '{alias}'...")
        resp = httpx.post(self.TOKEN_URL, data={
            "client_key":    self.client_key,
            "client_secret": self.client_secret,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        })

        if resp.status_code == 200 and "access_token" in resp.json():
            new_data = {**data, **resp.json()}
            new_data["expires_at"] = time.time() + new_data.get("expires_in", 86400)
            self._accounts[alias] = new_data
            self._save_all()
            return True

        logger.error(f"Token refresh failed for '{alias}': {resp.text}")
        return False

    # ─── Video Upload ─────────────────────────────────────────────────────────

    async def upload_video(self, video_path: str, alias: str, caption: str = "") -> dict:
        """Upload video to TikTok for a specific account alias."""
        if not self._refresh_account(alias):
            return {"success": False, "error": f"Cuenta '{alias}' no autenticada o token expirado."}

        access_token = self._accounts[alias]["access_token"]
        file_size = Path(video_path).stat().st_size

        # Step 1: Init upload
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        init_payload = {
            "post_info": {
                "title": caption[:2200] if caption else "📱 Subido con TikTok Bot",
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            }
        }

        async with httpx.AsyncClient(timeout=60) as client:
            init_resp = await client.post(self.UPLOAD_INIT_URL, json=init_payload, headers=headers)

        if init_resp.status_code != 200:
            return {"success": False, "error": f"Error al inicializar upload: {init_resp.text}"}

        init_data  = init_resp.json().get("data", {})
        upload_url = init_data.get("upload_url")
        publish_id = init_data.get("publish_id")

        if not upload_url:
            return {"success": False, "error": "No se recibió upload_url de TikTok"}

        # Step 2: Upload bytes
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        async with httpx.AsyncClient(timeout=120) as client:
            upload_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                    "Content-Length": str(file_size),
                }
            )

        if upload_resp.status_code not in (200, 201, 204):
            return {"success": False, "error": f"Error al subir video: {upload_resp.status_code}"}

        # Step 3: Poll status
        return await self._poll_publish_status(access_token, publish_id)

    async def _poll_publish_status(self, access_token: str, publish_id: str, max_tries: int = 10) -> dict:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        for attempt in range(max_tries):
            await asyncio.sleep(5)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.QUERY_POST_URL, json={"publish_id": publish_id}, headers=headers)

            if resp.status_code != 200:
                continue

            data   = resp.json().get("data", {})
            status = data.get("status")
            logger.info(f"Publish status [{attempt+1}/{max_tries}]: {status}")

            if status == "PUBLISH_COMPLETE":
                return {"success": True, "publish_id": publish_id}
            elif status in ("FAILED", "PUBLISH_FAILED"):
                return {"success": False, "error": f"TikTok rechazó el video: {data.get('fail_reason', 'Unknown')}"}

        return {"success": True, "publish_id": publish_id, "note": "Publicación en proceso"}
