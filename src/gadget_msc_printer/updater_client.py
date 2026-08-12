from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class UpdaterClientError(RuntimeError):
    """Raised when the local outbound update agent cannot complete a request."""


class UpdaterClient:
    """Small loopback-only client for ``jvlei-updater.service``.

    The updater binds only to 127.0.0.1.  The public HTTPS management service
    remains the sole browser-facing entry point and adds its existing login and
    CSRF checks before forwarding a request here.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int = 360,
    ) -> dict[str, Any]:
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                ) as response:
                    try:
                        data = await response.json(content_type=None)
                    except (ValueError, aiohttp.ClientError) as exc:
                        detail = await response.text()
                        raise UpdaterClientError(
                            detail or f"updater returned an invalid response: {exc}"
                        ) from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise UpdaterClientError(f"updater service is unavailable: {exc}") from exc
        if not isinstance(data, dict):
            raise UpdaterClientError("updater returned an invalid response")
        if response.status >= 400 or not data.get("ok", False):
            raise UpdaterClientError(str(data.get("error") or f"updater request failed: HTTP {response.status}"))
        return data

    async def status(self) -> dict[str, Any]:
        last_error: UpdaterClientError | None = None
        for delay in (0.0, 0.25, 0.5, 1.0):
            if delay:
                await asyncio.sleep(delay)
            try:
                result = await self._request("GET", "/status", timeout_seconds=10)
            except UpdaterClientError as exc:
                last_error = exc
                continue
            return {"available": True, **result}
        return {
            "ok": True,
            "available": False,
            "error": "升级代理正在启动或重载，请稍后刷新",
            "technical_error": str(last_error or "updater service is unavailable"),
        }

    async def check(self) -> dict[str, Any]:
        return await self._request("POST", "/check", {})

    async def download(self) -> dict[str, Any]:
        return await self._request("POST", "/download", {})

    async def install(self) -> dict[str, Any]:
        return await self._request("POST", "/install", {})

    async def rollback(self) -> dict[str, Any]:
        return await self._request("POST", "/rollback", {})

    async def configure(
        self,
        settings: dict[str, Any],
        organization: dict[str, str],
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/config",
            {"settings": settings, "organization": organization},
        )

    async def sync_terminal(self) -> dict[str, Any]:
        return await self._request("POST", "/sync-terminal", {})
