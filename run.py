"""
Single entry point — starts the entry pipeline in a background thread,
then runs the FastAPI/uvicorn server in the main thread.

Both share the same process, so core.frame_buffer works without any IPC.

Usage:
    python run.py
"""
import logging
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")


def _run_pipeline():
    try:
        from apps.entry_pipeline.main import run_pipeline
        run_pipeline()
    except Exception:
        log.exception("Pipeline crashed")


def _watchdog(pipeline_thread: threading.Thread, interval: float = 60.0) -> None:
    """Log a CRITICAL alert every `interval` seconds while the pipeline is dead."""
    while True:
        time.sleep(interval)
        if not pipeline_thread.is_alive():
            log.critical(
                "WATCHDOG: pipeline thread has died — "
                "face recognition is offline. Restart the process to recover."
            )


if __name__ == "__main__":
    import uvicorn

    # Start the pipeline in a daemon thread so it dies when the server exits.
    t = threading.Thread(target=_run_pipeline, daemon=True, name="pipeline")
    t.start()
    log.info("Pipeline thread started")

    # Watchdog: logs CRITICAL if the pipeline thread dies unexpectedly.
    wd = threading.Thread(target=_watchdog, args=(t,), daemon=True, name="watchdog")
    wd.start()

    # Run the API server in the main thread.
    uvicorn.run(
        "apps.api_server.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
