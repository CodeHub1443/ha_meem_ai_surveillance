"""
Single entry point — starts the entry pipeline in a background thread,
then runs the FastAPI/uvicorn server in the main thread.

Both share the same process, so core.frame_buffer works without any IPC.

Usage:
    python run.py
"""
import logging
import threading

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


if __name__ == "__main__":
    import uvicorn

    # Start the pipeline in a daemon thread so it dies when the server exits.
    t = threading.Thread(target=_run_pipeline, daemon=True, name="pipeline")
    t.start()
    log.info("Pipeline thread started")

    # Run the API server in the main thread.
    uvicorn.run(
        "apps.api_server.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
