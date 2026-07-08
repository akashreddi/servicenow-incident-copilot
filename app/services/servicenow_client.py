"""Async ServiceNow Table API client with OAuth 2.0 token management.

Demonstrates: httpx.AsyncClient, OAuth token refresh with expiry buffer,
Table API queries (sysparm_query), dot-walked display values, PATCH updates.
"""
import logging
import time
from typing import Any, Optional

import httpx

from app.config import Settings
from app.models import Incident

logger = logging.getLogger(__name__)


class ServiceNowClient:
    def __init__(self, settings: Settings):
        self._s = settings
        self._base = settings.snow_instance_url.rstrip("/")
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._http = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- OAuth ----------
    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:  # 60s buffer
            return self._token
        data: dict[str, str] = {
            "grant_type": self._s.snow_oauth_grant_type,
            "client_id": self._s.snow_oauth_client_id,
            "client_secret": self._s.snow_oauth_client_secret,
        }
        if self._s.snow_oauth_grant_type == "password":
            data |= {"username": self._s.snow_username, "password": self._s.snow_password}
        resp = await self._http.post("/oauth_token.do", data=data)
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 1800))
        logger.info("Obtained ServiceNow OAuth token (expires_in=%s)", payload.get("expires_in"))
        return self._token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._get_token()}", "Accept": "application/json"}

    # ---------- Table API ----------
    async def get_incident(self, sys_id: str) -> Incident:
        resp = await self._http.get(
            f"/api/now/table/incident/{sys_id}",
            headers=await self._headers(),
            params={"sysparm_display_value": "true", "sysparm_exclude_reference_link": "true"},
        )
        resp.raise_for_status()
        return Incident(**self._pick(resp.json()["result"]))

    async def list_incidents(self, query: str = "active=true", limit: int = 50) -> list[Incident]:
        resp = await self._http.get(
            "/api/now/table/incident",
            headers=await self._headers(),
            params={
                "sysparm_query": query,
                "sysparm_limit": limit,
                "sysparm_display_value": "true",
                "sysparm_exclude_reference_link": "true",
            },
        )
        resp.raise_for_status()
        return [Incident(**self._pick(r)) for r in resp.json()["result"]]

    async def update_incident(self, sys_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http.patch(
            f"/api/now/table/incident/{sys_id}",
            headers=await self._headers(),
            json=fields,
        )
        resp.raise_for_status()
        return resp.json()["result"]

    async def add_work_note(self, sys_id: str, note: str) -> None:
        await self.update_incident(sys_id, {"work_notes": note})

    async def resolve_group_sys_id(self, group_name: str) -> Optional[str]:
        """Look up sys_user_group sys_id by exact name (needed to set assignment_group)."""
        resp = await self._http.get(
            "/api/now/table/sys_user_group",
            headers=await self._headers(),
            params={"sysparm_query": f"name={group_name}", "sysparm_limit": 1, "sysparm_fields": "sys_id,name"},
        )
        resp.raise_for_status()
        results = resp.json()["result"]
        return results[0]["sys_id"] if results else None

    async def create_incident(self, fields: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http.post("/api/now/table/incident", headers=await self._headers(), json=fields)
        resp.raise_for_status()
        return resp.json()["result"]

    # ---------- helpers ----------
    @staticmethod
    def _pick(raw: dict[str, Any]) -> dict[str, Any]:
        keys = Incident.model_fields.keys()
        out: dict[str, Any] = {}
        for k in keys:
            v = raw.get(k, "")
            # display_value=true can return dicts for reference fields
            out[k] = v.get("display_value", "") if isinstance(v, dict) else (v or "")
        return out
