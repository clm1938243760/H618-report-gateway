from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from aiohttp import web

from .server import CenterApp, CenterConfig, create_ssl_context


def install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> bool:
    """Register POSIX shutdown handlers when the event loop supports them."""
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    except (NotImplementedError, RuntimeError):
        return False
    return True


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="JVLEI Windows update center")
    parser.add_argument("--config", default="update_center/config.yaml")
    args = parser.parse_args()
    config = CenterConfig.load(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = CenterApp(config)
    admin_runner = web.AppRunner(app.admin_app, access_log=None)
    device_runner = web.AppRunner(app.device_app, access_log=None)
    await admin_runner.setup()
    await device_runner.setup()
    await web.TCPSite(admin_runner, config.admin_host, config.admin_port, ssl_context=create_ssl_context(config)).start()
    await web.TCPSite(device_runner, config.device_host, config.device_port).start()
    logging.info("admin UI: https://%s:%s", config.admin_host, config.admin_port)
    logging.info("device API: http://%s:%s", config.device_host, config.device_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    install_signal_handlers(loop, stop)
    try:
        await stop.wait()
    finally:
        await admin_runner.cleanup()
        await device_runner.cleanup()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
