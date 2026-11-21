"""Local-only test UI gateway. Never mount this app on the production ML API."""

import json
import logging
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.dataset import read_manifest
from mediamesh_ml.jobs import LocalJobStore, initialize_local_jobs
from mediamesh_ml.media import LocalMediaSource
from mediamesh_ml.schemas import SearchRequest

logger = logging.getLogger(__name__)


def display_name(reference: str) -> str:
    name = Path(reference).name
    if re.match(r"ui-[0-9a-f]{32}-", name):
        return name.split("-", 2)[2]
    if name.startswith("ui-retry-"):
        return "Retry test image"
    if name.startswith("demo-retry-"):
        return "CLI retry demo image"
    return name


class SampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sampleId: str | None = None


def create_app(
    settings: Settings | None = None,
    *,
    static_root: Path | None = None,
    evaluation_root: Path | None = None,
    api_url: str | None = None,
):
    settings = settings or Settings()
    static_root = static_root or Path("dev-ui")
    evaluation_root = evaluation_root or Path("evaluation")
    api_url = (api_url or os.getenv("ML_DEV_API_URL", "http://ml-api:8000")).rstrip("/")
    store = LocalJobStore(settings)

    @asynccontextmanager
    async def lifespan(app):
        app.state.local_ready = False
        try:
            initialize_local_jobs(settings)  # Refuses anything except minimal local fixtures.
            app.state.local_ready = True
        except Exception as error:
            logger.warning("Local UI setup unavailable: %s", type(error).__name__)
        yield

    app = FastAPI(
        title="MediaMesh local test console",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_local():
        if not app.state.local_ready:
            raise HTTPException(503, "Initialize the standalone local database fixtures first")

    def proxy(path, body=None):
        request = urllib.request.Request(
            api_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read(2_000_000))
        except (OSError, ValueError):
            return 503, {"error": {"message": "ML API is unavailable"}}

    def samples():
        found = []
        for name, kind in [("manifest.json", "image"), ("video-manifest.json", "video")]:
            for item in read_manifest(evaluation_root / name):
                if (settings.media_root / item["filename"]).is_file():
                    found.append({**item, "mediaType": kind})
        return found

    def register(aid):
        with connection(settings) as conn:
            conn.execute("INSERT INTO assets(id) VALUES (%s) ON CONFLICT DO NOTHING", (aid,))

    def reference(aid):
        with connection(settings) as conn:
            row = conn.execute(
                "SELECT media_reference, media_type FROM ml_dev.index_jobs WHERE asset_id=%s "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (aid,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "No local media reference for this asset")
        return row

    def queue_sample(item):
        with connection(settings) as conn:
            existing = conn.execute(
                "SELECT asset_id FROM ml_dev.index_jobs WHERE media_reference=%s "
                "ORDER BY created_at, id LIMIT 1",
                (item["filename"],),
            ).fetchone()
        aid = (
            existing[0] if existing else uuid5(NAMESPACE_URL, "mediamesh-ui:" + item["source_page"])
        )
        register(aid)
        jid = store.enqueue(aid, item["filename"], item["mediaType"])
        return {"assetId": str(aid), "jobId": str(jid)}

    @app.middleware("http")
    async def no_cache(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is not None:
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin != expected:
                return JSONResponse(
                    status_code=403, content={"detail": "Use this local console directly"}
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _error):
        return JSONResponse(status_code=400, content={"detail": "Invalid request input"})

    @app.exception_handler(Exception)
    async def unavailable(_request, error):
        logger.warning("Local console operation failed: %s", type(error).__name__)
        return JSONResponse(
            status_code=503, content={"detail": "Local operation failed; check service logs"}
        )

    @app.get("/")
    def index():
        return FileResponse(static_root / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/dev/status")
    def status():
        api_code, _ = proxy("/health")
        ready_code, _ = proxy("/ready")
        return {
            "api": api_code == 200,
            "ready": ready_code == 200,
            "localFixtures": app.state.local_ready,
            "maxUploadBytes": settings.media_max_bytes,
        }

    @app.get("/dev/samples")
    def get_samples():
        require_local()
        return {
            "samples": [
                {
                    "id": i["id"],
                    "name": i["filename"],
                    "title": i["title"],
                    "mediaType": i["mediaType"],
                    "source": i["source_page"],
                    "credit": i["creator"],
                    "license": i["license"],
                }
                for i in samples()
            ]
        }

    @app.post("/dev/samples/index", status_code=202)
    def index_samples(body: SampleRequest):
        require_local()
        selected = [i for i in samples() if body.sampleId is None or i["id"] == body.sampleId]
        if not selected:
            raise HTTPException(404, "Sample is not downloaded locally")
        return {"jobs": [queue_sample(i) for i in selected]}

    @app.get("/dev/assets")
    def assets():
        require_local()
        with connection(settings) as conn:
            rows = conn.execute(
                "SELECT a.id, j.media_reference, j.media_type, s.processing_status, "
                "(SELECT count(*) FROM asset_vectors v WHERE v.asset_id=a.id) "
                "FROM public.assets a JOIN LATERAL (SELECT media_reference, media_type "
                "FROM ml_dev.index_jobs WHERE asset_id=a.id "
                "ORDER BY created_at DESC,id DESC LIMIT 1) j ON true "
                "LEFT JOIN ml_dev.asset_states s ON s.asset_id=a.id ORDER BY a.id LIMIT 500"
            ).fetchall()
        return {
            "assets": [
                {
                    "assetId": str(r[0]),
                    "name": display_name(r[1]),
                    "mediaType": r[2],
                    "status": (r[3] or "INDEXED")
                    if r[4] or r[3] in {"PROCESSING", "FAILED"}
                    else "NOT_INDEXED",
                    "vectorCount": r[4],
                }
                for r in rows
            ]
        }

    @app.get("/dev/jobs")
    def jobs():
        require_local()
        with connection(settings) as conn:
            rows = conn.execute(
                "SELECT id,asset_id,media_reference,media_type,status,attempts,"
                "max_attempts,last_error "
                "FROM ml_dev.index_jobs ORDER BY created_at DESC,id DESC LIMIT 50"
            ).fetchall()
        return {
            "jobs": [
                {
                    "jobId": str(r[0]),
                    "assetId": str(r[1]),
                    "name": display_name(r[2]),
                    "mediaType": r[3],
                    "status": r[4],
                    "attempts": r[5],
                    "maxAttempts": r[6],
                    "lastError": r[7],
                }
                for r in rows
            ]
        }

    @app.post("/dev/assets/{aid}/reindex", status_code=202)
    def reindex(aid: UUID):
        require_local()
        ref, kind = reference(aid)
        return {"jobId": str(store.enqueue(aid, ref, kind))}

    @app.delete("/dev/assets/{aid}/index")
    def remove_index(aid: UUID):
        require_local()
        with connection(settings) as conn:
            if not conn.execute("SELECT id FROM assets WHERE id=%s FOR UPDATE", (aid,)).fetchone():
                raise HTTPException(404, "Asset not found")
            if conn.execute(
                "SELECT id FROM ml_dev.index_jobs WHERE asset_id=%s "
                "AND status IN ('PENDING','PROCESSING')",
                (aid,),
            ).fetchone():
                raise HTTPException(409, "Wait for the active job before removing its index")
            conn.execute("DELETE FROM asset_vectors WHERE asset_id=%s", (aid,))
        return {"removed": True}

    @app.get("/dev/media/{aid}")
    def media(aid: UUID):
        require_local()
        ref, _ = reference(aid)
        try:
            with LocalMediaSource(
                settings.media_root, max_bytes=settings.media_max_bytes
            ).materialize(ref) as path:
                return FileResponse(
                    path,
                    media_type=mimetypes.guess_type(path.name)[0],
                    content_disposition_type="inline",
                )
        except (OSError, ValueError):
            raise HTTPException(404, "Local media file is unavailable") from None

    @app.post("/dev/upload", status_code=202)
    async def upload(
        request: Request, filename: str = "upload.jpg", kind: Literal["image", "video"] = "image"
    ):
        require_local()
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[-100:]
        allowed = {
            "image": {".jpg", ".jpeg", ".png", ".webp"},
            "video": {".mp4", ".mov", ".webm", ".mkv"},
        }
        if Path(name).suffix.lower() not in allowed[kind]:
            raise HTTPException(400, "Unsupported file extension for the selected media type")
        aid = uuid4()
        dest = settings.media_root / f"ui-{aid.hex}-{name}"
        partial = dest.with_suffix(dest.suffix + ".part")
        size = 0
        try:
            with partial.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > settings.media_max_bytes:
                        raise HTTPException(413, "File exceeds the upload size limit")
                    output.write(chunk)
            if size == 0:
                raise HTTPException(400, "File is empty")
            partial.replace(dest)
            register(aid)
            jid = store.enqueue(aid, dest.name, kind)
        except BaseException:
            partial.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            raise
        return {"assetId": str(aid), "jobId": str(jid)}

    def restore_retry_file(jid, dest):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = store.status(jid)
            if state["status"] == "FAILED":
                return
            if state["attempts"] >= 1 and state["status"] == "PENDING":
                dest.write_bytes((settings.media_root / "elephant-02.jpg").read_bytes())
                return
            time.sleep(0.1)

    @app.post("/dev/retry-demo", status_code=202)
    def retry_demo(tasks: BackgroundTasks):
        require_local()
        if (
            settings.job_max_attempts < 2
            or min(settings.job_retry_base_seconds, settings.job_retry_max_seconds) < 1
        ):
            raise HTTPException(
                400, "Retry demo needs two attempts and at least a one-second delay"
            )
        if not (settings.media_root / "elephant-02.jpg").is_file():
            raise HTTPException(400, "Download the elephant-02 image sample first")
        aid = uuid4()
        dest = settings.media_root / f"ui-retry-{aid.hex}.jpg"
        register(aid)
        jid = store.enqueue(aid, dest.name, "image")
        tasks.add_task(restore_retry_file, jid, dest)
        return {"jobId": str(jid), "assetId": str(aid)}

    @app.post("/dev/search")
    def search(body: SearchRequest):
        require_local()
        code, result = proxy("/internal/search", body.model_dump())
        return JSONResponse(status_code=code, content=result)

    app.mount("/static", StaticFiles(directory=static_root), name="static")
    return app
