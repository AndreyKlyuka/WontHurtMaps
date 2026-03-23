from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler()


def run_pipeline() -> None:
    logger.info("Pipeline job triggered (placeholder — no stages implemented yet)")


def shutdown(signum: int, frame: object) -> None:
    logger.info("Received shutdown signal, stopping scheduler")
    scheduler.shutdown(wait=False)
    sys.exit(0)


def main() -> None:
    scheduler.add_job(
        run_pipeline,
        "interval",
        minutes=settings.pipeline_interval_minutes,
        id="pipeline",
    )
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    logger.info(
        "Starting WontHurtMaps Worker, pipeline interval=%d min",
        settings.pipeline_interval_minutes,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
