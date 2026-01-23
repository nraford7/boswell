"""Entry point for running the voice worker.

This module allows running the voice worker as a module:
    python -m boswell.server.worker

The worker polls for guests with active interviews (status="started")
and runs Pipecat voice pipelines for each interview.
"""

import asyncio
import logging
import signal
import sys

from boswell.server.worker import run_voice_worker, shutdown_voice_worker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point for the voice worker."""
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        shutdown_event.set()

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    logger.info("Starting Boswell voice worker")

    # Run the worker until shutdown signal
    worker_task = asyncio.create_task(run_voice_worker())

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("Initiating graceful shutdown...")
    worker_task.cancel()

    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    await shutdown_voice_worker()
    logger.info("Voice worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
