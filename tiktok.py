import os
import json
import time
import logging
import httpx
import asyncio
from pathlib import Path
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

TOKEN_FILE = "tiktok_token.json"

class TikTokUploader:
    """
    Handles TikTok OAuth2 and video uploads via the Content Posting API.
    Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
    """

    AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    QUERY_POST_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self):
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
        self.redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "https://localhost/callback")
        self._token_data = self._load_token()

    # ─── Token Management ─────────────────────────────────────────────────────

    def _load_token(self) -> dict:
        if Path(TOKEN_FILE).exists():
            with open(TOKEN_FILE) as f:
                return json.load(f)
        return {}

    def _save_token(self, data: dict):
        self._token_data = data
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Token saved.")

    def is_authenticated(self) -> bool:
        if not self._token_data.get("access_token"):
            return False
        expires_at = self._token_data.get("expires_at", 0)
        return time.time() < expires_at

    def _refresh_if_needed(self) -> bool:
        """Refresh access token using refresh_token if expired."""
        if self.is_authenticated():
            return True

        refresh_token = self._token_data.get("refresh_token")
        if not refresh_token:
            return False

        logger.info("Access token expired. Refreshing...")
        resp = httpx.post(self.TOKEN_URL, data={
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

        if resp.status_code == 200:
            data = resp.json()
            data["expires_at"] = time.time() + data.get("expires_in", 86400)
            self._save_token(data)
            return True

        logger.error(f"Token refresh failed: {resp.text}")
        return False

    # ─── OAuth Flow ───────────────────────────────────────────────────────────

    def get_auth_url(self) -> str:
        params = {
            "client_key": self.client_key,
            "scope": "user.info.basic,video.publish,video.upload",
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": "telegram_bot",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> bool:
        """Exchange OAuth code for access token."""
        resp = httpx.post(self.TOKEN_URL, data={
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        })

        if resp.status_code == 200:
            data = resp.json()
            if "access_token" in data:
                data["expires_at"] = time.time() + data.get("expires_in", 86400)
                self._save_token(data)
                return True

        logger.error(f"Code exchange failed: {resp.text}")
        return False

    # ─── Video Upload ─────────────────────────────────────────────────────────

    async def upload_video(self, video_path: str, caption: str = "") -> dict:
        """
        Upload video to TikTok using the FILE_UPLOAD method.
        Returns dict with 'success' bool and optionally 'error' or 'publish_id'.
        """
        if not self._refresh_if_needed():
            return {"success": False, "error": "No autenticado. Usa /auth"}

        access_token = self._token_data["access_token"]
        file_size = Path(video_path).stat().st_size

        # Step 1: Initialize upload
        init_payload = {
            "post_info": {
                "title": caption[:2200] if caption else "📱 Subido con TikTok Bot",
                "privacy_level": "SELF_ONLY",  # Change to PUBLIC_TO_EVERYONE when ready
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

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            init_resp = await client.post(
                self.UPLOAD_INIT_URL,
                json=init_payload,
                headers=headers
            )

        if init_resp.status_code != 200:
            logger.error(f"Init upload failed: {init_resp.text}")
            return {"success": False, "error": f"Error al inicializar upload: {init_resp.text}"}

        init_data = init_resp.json().get("data", {})
        upload_url = init_data.get("upload_url")
        publish_id = init_data.get("publish_id")

        if not upload_url:
            return {"success": False, "error": "No se recibió upload_url de TikTok"}

        # Step 2: Upload video bytes
        logger.info(f"Uploading video to TikTok: {video_path}")
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        upload_headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Length": str(file_size),
        }

        async with httpx.AsyncClient(timeout=120) as client:
            upload_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers=upload_headers
            )

        if upload_resp.status_code not in (200, 201, 204):
            logger.error(f"Video upload failed: {upload_resp.text}")
            return {"success": False, "error": f"Error al subir video: {upload_resp.status_code}"}

        # Step 3: Poll for publish status
        logger.info(f"Video uploaded. Polling publish status for: {publish_id}")
        status = await self._poll_publish_status(access_token, publish_id)

        return status

    async def _poll_publish_status(self, access_token: str, publish_id: str, max_tries: int = 10) -> dict:
        """Poll TikTok until video is published or fails."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        for attempt in range(max_tries):
            await asyncio.sleep(5)  # wait 5s between polls

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self.QUERY_POST_URL,
                    json={"publish_id": publish_id},
                    headers=headers
                )

            if resp.status_code != 200:
                continue

            data = resp.json().get("data", {})
            process_status = data.get("status")

            logger.info(f"Publish status [{attempt+1}/{max_tries}]: {process_status}")

            if process_status == "PUBLISH_COMPLETE":
                return {"success": True, "publish_id": publish_id}
            elif process_status in ("FAILED", "PUBLISH_FAILED"):
                fail_reason = data.get("fail_reason", "Unknown")
                return {"success": False, "error": f"TikTok rechazó el video: {fail_reason}"}

        return {"success": True, "publish_id": publish_id, "note": "Publicación en proceso"}
