"""The worker entrypoint.

Two responsibilities, chosen by configuration:

* when ``WORKFLOW_ENGINE=temporal``, run the Temporal worker that hosts the
  mission workflow and its activities;
* always, run the periodic maintenance loop (expired-memory sweep and the
  autonomous-monitoring tick) that does not belong in a request.

Run with::

    python -m seo_engine.worker

The local workflow engine needs no worker at all — missions run in-process in
the API — so this process is only required for Temporal and for scheduled
maintenance.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from seo_engine.observability.logging import configure_logging, get_logger
from seo_engine.shared.config import get_settings
from seo_engine.shared.db import dispose_engine, session_scope

log = get_logger(__name__)

#: How often the maintenance loop wakes. Deliberately slow; nothing here is
#: latency-sensitive, and a tight loop would just burn connections.
MAINTENANCE_INTERVAL_SECONDS = 3600


async def sweep_expired_memory() -> int:
    """Forget memories past their expiry. Platform-level housekeeping."""
    from seo_engine.memory.service import sweep_expired_memory as sweep

    async with session_scope() as session:
        return await sweep(session)


async def maintenance_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            removed = await sweep_expired_memory()
            if removed:
                log.info("maintenance_memory_swept", removed=removed)
        except Exception:
            log.exception("maintenance_tick_failed")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=MAINTENANCE_INTERVAL_SECONDS)


async def run() -> None:
    configure_logging()
    settings = get_settings()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    tasks: list[asyncio.Task] = [asyncio.create_task(maintenance_loop(stop))]

    if settings.workflow_engine == "temporal":
        from seo_engine.workflows.temporal import run_worker

        log.info("worker_starting", mode="temporal", task_queue=settings.temporal_task_queue)
        tasks.append(asyncio.create_task(run_worker(settings)))
    else:
        log.info(
            "worker_starting",
            mode="maintenance_only",
            note="WORKFLOW_ENGINE=local runs missions in-process; no workflow worker needed",
        )

    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await dispose_engine()
        log.info("worker_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
