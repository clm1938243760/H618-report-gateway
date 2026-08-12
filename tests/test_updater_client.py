from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from gadget_msc_printer.updater_client import UpdaterClient, UpdaterClientError


class UpdaterClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_retries_transient_agent_restart(self) -> None:
        client = UpdaterClient()
        client._request = AsyncMock(
            side_effect=[
                UpdaterClientError("connection refused"),
                UpdaterClientError("connection refused"),
                {"ok": True, "current_version": "v0.22.4"},
            ]
        )

        with patch("gadget_msc_printer.updater_client.asyncio.sleep", new=AsyncMock()) as sleep:
            status = await client.status()

        self.assertTrue(status["available"])
        self.assertEqual(status["current_version"], "v0.22.4")
        self.assertEqual(client._request.await_count, 3)
        self.assertEqual(sleep.await_count, 2)

    async def test_status_reports_concise_error_after_retry_window(self) -> None:
        client = UpdaterClient()
        client._request = AsyncMock(side_effect=UpdaterClientError("connection refused"))

        with patch("gadget_msc_printer.updater_client.asyncio.sleep", new=AsyncMock()):
            status = await client.status()

        self.assertFalse(status["available"])
        self.assertEqual(status["error"], "升级代理正在启动或重载，请稍后刷新")
        self.assertEqual(status["technical_error"], "connection refused")
        self.assertEqual(client._request.await_count, 4)


if __name__ == "__main__":
    unittest.main()
