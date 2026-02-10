"""Entry point for running the background jobs worker.

This module allows running the jobs worker as a module:
    python -m boswell.server.jobs_main

The worker polls the job_queue table for pending jobs and processes them
using registered handlers (generate_analysis, send_email, generate_questions).
"""

import asyncio
import logging
import signal
import sys

from boswell.server.jobs import run_worker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point for the jobs worker."""
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        shutdown_event.set()

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    logger.info("Starting Boswell jobs worker")

    # Run the worker until shutdown signal or unexpected exit
    worker_task = asyncio.create_task(run_worker())

    # Wait for either shutdown signal or worker task completion
    shutdown_waiter = asyncio.create_task(shutdown_event.wait())
    done, _ = await asyncio.wait(
        [worker_task, shutdown_waiter],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if worker_task in done:
        shutdown_waiter.cancel()
        exc = worker_task.exception()
        if exc:
            logger.error(f"Jobs worker exited with error: {exc}")
            sys.exit(1)
        else:
            logger.error("Jobs worker exited unexpectedly without error")
            sys.exit(1)

    # Graceful shutdown via signal
    logger.info("Initiating graceful shutdown...")
    worker_task.cancel()

    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    logger.info("Jobs worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
