from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import ssl
from pathlib import Path

from aiohttp import web

from .auth import SessionStore
from .config import load_config
from .cups_manager import CupsManager
from .driver_manager import DriverManager
from .maintenance import MaintenanceManager
from .physical_print import PhysicalPrintWorker
from .report_info import ReportInfoManager
from .report_upload import ReportUploadWorker
from .web import ConfigWebApp


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="K2B H618 report gateway configuration web service")
    parser.add_argument("--config", default="/etc/gadget-msc-printer/config.yaml")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    logging.basicConfig(
        level=getattr(logging, config.runtime.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    report_info = ReportInfoManager(config.device)
    await asyncio.to_thread(report_info.ensure)
    uploader = ReportUploadWorker(config.upload, config.pdf, report_info)
    driver_manager = DriverManager()
    cups = CupsManager(custom_profile_provider=driver_manager.profiles)
    physical_printer = PhysicalPrintWorker(config.physical_printer, config.pdf, cups)
    maintenance = MaintenanceManager(
        config.cleanup,
        config.runtime,
        config.pdf,
        config.printer,
        config.msc,
        uploader.store,
    )
    application = ConfigWebApp(
        config_path,
        config,
        SessionStore(config.web.session_hours),
        report_info,
        uploader,
        maintenance,
        cups=cups,
        physical_printer=physical_printer,
        driver_manager=driver_manager,
    )
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(config.web.tls_cert, config.web.tls_key)
    runner = web.AppRunner(application.app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.web.host, config.web.port, ssl_context=ssl_context)
    await site.start()
    listening_ports = [config.web.port]
    if config.web.compatibility_port:
        compatibility_site = web.TCPSite(
            runner,
            config.web.host,
            config.web.compatibility_port,
            ssl_context=ssl_context,
        )
        await compatibility_site.start()
        listening_ports.append(config.web.compatibility_port)
    logging.getLogger(__name__).info(
        "configuration web listening on https://%s ports %s",
        config.web.host,
        ", ".join(str(port) for port in listening_ports),
    )
    upload_task = asyncio.create_task(uploader.run())
    maintenance_task = asyncio.create_task(maintenance.run())
    hotspot_task = asyncio.create_task(application.monitor_hotspot())
    physical_print_task = asyncio.create_task(physical_printer.run())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    uploader.stop()
    maintenance.stop()
    physical_printer.stop()
    upload_task.cancel()
    maintenance_task.cancel()
    hotspot_task.cancel()
    physical_print_task.cancel()
    await asyncio.gather(
        upload_task,
        maintenance_task,
        hotspot_task,
        physical_print_task,
        return_exceptions=True,
    )
    await runner.cleanup()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
