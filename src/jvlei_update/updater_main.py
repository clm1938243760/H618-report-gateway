from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from aiohttp import web

from .package import PackageError
from .updater import UpdaterConfig, UpdaterError, UpdaterService


def create_local_app(service: UpdaterService) -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)

    async def status(request: web.Request) -> web.Response:
        return web.json_response(service.status())

    async def check(request: web.Request) -> web.Response:
        try:
            result = await service.check_once(auto_execute=False)
            update = result.get("update")
            if isinstance(update, dict) and update.get("auto_upgrade") is True:
                result = service.start_auto_update()
                return web.json_response(result, status=202)
        except (UpdaterError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result)

    async def download(request: web.Request) -> web.Response:
        try:
            result = await service.download_update()
        except (UpdaterError, PackageError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result)

    async def install(request: web.Request) -> web.Response:
        try:
            result = service.start_install()
        except (UpdaterError, PackageError, OSError) as exc:
            logging.getLogger(__name__).exception("update installation failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result, status=202)

    async def rollback(request: web.Request) -> web.Response:
        try:
            result = service.start_rollback()
        except (UpdaterError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result, status=202)

    async def configure(request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            organization = payload.get("organization")
            if not isinstance(organization, dict):
                raise UpdaterError("organization must be an object")
            result = await service.configure_company(str(payload.get("center_url", "")), organization)
        except (UpdaterError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result)

    async def sync_terminal(request: web.Request) -> web.Response:
        try:
            result = await service.report_terminal_info()
        except (UpdaterError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result)

    app.add_routes(
        [
            web.get("/status", status),
            web.post("/check", check),
            web.post("/download", download),
            web.post("/install", install),
            web.post("/rollback", rollback),
            web.post("/sync-terminal", sync_terminal),
            web.put("/config", configure),
        ]
    )
    return app


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="JVLEI H618 outbound update agent")
    parser.add_argument("--config", default="/etc/jvlei-updater/config.yaml")
    args = parser.parse_args()
    config = UpdaterConfig.load(args.config)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = UpdaterService(args.config, config)
    runner = web.AppRunner(create_local_app(service), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.local_api_host, config.local_api_port)
    await site.start()
    boot_task = asyncio.create_task(service.run_boot_check())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    service.stop()
    boot_task.cancel()
    await asyncio.gather(boot_task, return_exceptions=True)
    await runner.cleanup()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
