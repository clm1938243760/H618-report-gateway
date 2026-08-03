from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .config import is_msc_mode, load_config
from .msc_monitor import MscMonitor
from .pdf_converter import PdfConverter
from .print_capture import PrintCapture


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="K2B H618 MSC/Printer report collector")
    parser.add_argument("--config", default="/etc/gadget-msc-printer/config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, config.runtime.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    converter = PdfConverter(config.pdf) if config.pdf.enabled else None
    collector = (
        MscMonitor(config.msc, converter)
        if is_msc_mode(config.gadget.mode)
        else PrintCapture(config.printer, converter)
    )
    logging.getLogger(__name__).info("collector mode: %s", config.gadget.mode)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    task = asyncio.create_task(collector.run())
    await stop.wait()
    collector.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
