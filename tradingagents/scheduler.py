"""Lightweight in-process interval scheduler for background collectors.

Runs periodic jobs inside the same asyncio event loop as the FastAPI app
(uvicorn), instead of a separate cron daemon. This sidesteps hosting
platforms whose scheduled-job product can't see the persistent disk the web
process itself writes to (a real limitation on Render/Railway at this
project's scale) and keeps the deployment to a single process.

Each job is a plain sync callable (all current collectors use urllib, which
blocks) — it runs via `asyncio.to_thread` so a slow collector call doesn't
stall the event loop's request handling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    run: Callable[[], None]
    run_immediately: bool = True


async def _run_job_forever(job: ScheduledJob) -> None:
    if not job.run_immediately:
        await asyncio.sleep(job.interval_seconds)
    while True:
        try:
            await asyncio.to_thread(job.run)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled job %s failed", job.name)
        await asyncio.sleep(job.interval_seconds)


def start_scheduler(jobs: list[ScheduledJob]) -> list[asyncio.Task]:
    """Start each job as a background asyncio task.

    Returns the tasks so the caller can cancel them on shutdown (e.g. from a
    FastAPI lifespan context manager).
    """
    return [asyncio.create_task(_run_job_forever(job), name=f"scheduler:{job.name}") for job in jobs]


async def stop_scheduler(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
