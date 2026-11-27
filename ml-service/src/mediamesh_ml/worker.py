"""Local indexing worker with lease renewal and graceful drain on shutdown."""

import argparse
import logging
import signal
import threading
from contextlib import contextmanager

from PIL import UnidentifiedImageError

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import JobStore
from mediamesh_ml.embeddings import ClipEngine
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.jobs import PostgresJobStore, StaleClaim
from mediamesh_ml.logging_json import configure_logging, request_id
from mediamesh_ml.media import AzureBlobMediaSource, LocalMediaSource
from mediamesh_ml.playback import PlaybackPublisher
from mediamesh_ml.vectors import PgVectorRepository
from mediamesh_ml.video import VideoSampler

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store: JobStore, indexer: IndexingService, settings: Settings):
        self.store = store
        self.indexer = indexer
        self.settings = settings

    @contextmanager
    def maintain_lease(self, job):
        done = threading.Event()
        lost = threading.Event()

        def renew():
            while not done.wait(min(10, self.settings.job_lease_seconds / 3)):
                try:
                    if not self.store.renew(job):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    logger.warning("Lease renewal failed for job %s", job.job_id)
                    return

        thread = threading.Thread(target=renew, name="job-lease", daemon=True)
        thread.start()
        try:
            yield lost
        finally:
            done.set()
            thread.join()

    def run_once(self) -> bool:
        job = self.store.claim()
        if job is None:
            return False
        correlation = request_id.set("job-" + str(job.job_id))
        try:
            with self.maintain_lease(job) as lost:
                playback_key = None
                if job.media_type == "image":
                    records = self.indexer.prepare_image(job.asset_id, job.media_reference)
                else:
                    records, playback_key = self.indexer.prepare_video_job(
                        job.asset_id, job.media_reference
                    )
                if lost.is_set():
                    raise StaleClaim("Lease renewal lost")
                self.store.complete(job, records, playback_key=playback_key)
            logger.info("Completed job %s on attempt %s", job.job_id, job.attempt)
        except StaleClaim:
            logger.warning("Discarded stale result for job %s", job.job_id)
        except Exception as error:
            retryable = not isinstance(error, (ValueError, UnidentifiedImageError))
            if isinstance(error, ValueError) and "timed out" in str(error):
                retryable = True
            try:
                self.store.fail(job, type(error).__name__, retryable=retryable)
            except StaleClaim:
                logger.warning("Failure report discarded for stale job %s", job.job_id)
            logger.warning("Job %s failed: %s", job.job_id, type(error).__name__)
        finally:
            request_id.reset(correlation)
        return True

    def run(self, stop: threading.Event):
        while not stop.is_set():
            try:
                if not self.run_once():
                    stop.wait(self.settings.worker_poll_seconds)
            except Exception as error:
                # A DB outage leaves any active claim recoverable after lease expiry.
                logger.warning("Worker unavailable: %s", type(error).__name__)
                stop.wait(self.settings.worker_poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Attempt one available job and exit")
    args = parser.parse_args()
    settings = Settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    engine = ClipEngine(settings)
    engine.load()  # Reuse one model across jobs; do not lease a job during model startup.
    source = (
        AzureBlobMediaSource(settings)
        if settings.production_mode
        else LocalMediaSource(settings.media_root, max_bytes=settings.media_max_bytes)
    )
    sampler = VideoSampler(settings)
    worker = Worker(
        PostgresJobStore(settings),
        IndexingService(
            engine,
            source,
            PgVectorRepository(settings),
            sampler,
            # Only the catalog (Blob) source can store derived playback copies.
            PlaybackPublisher(settings, source, sampler) if settings.production_mode else None,
        ),
        settings,
    )
    if args.once:
        if not stop.is_set():
            worker.run_once()
    else:
        worker.run(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
