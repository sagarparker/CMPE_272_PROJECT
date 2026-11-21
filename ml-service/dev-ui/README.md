# Simple local ML test console

Plain HTML/CSS/JavaScript, served by a separate FastAPI development gateway.
No frontend build tools or external assets. The production `frontend/` remains
untouched and the original ML `/internal/search` request/response is unchanged.

## Start and stop with one script

From the repository root:

```bash
./ml-service/manage.sh start
./ml-service/manage.sh stop
```

The script also supports `restart`, `status`, and `logs [SERVICE]`. It waits for
readiness and preserves stored data when stopped. Docker Desktop must be running.
See [LOCAL_WORKFLOW.md](../LOCAL_WORKFLOW.md) for setup details and all commands.

From `ml-service/`, after the database/model setup in `LOCAL_WORKFLOW.md`:

```bash
docker compose build ml-api ml-tools
ML_MODEL_OFFLINE=true docker compose --profile worker --profile ui up -d --wait ml-api ml-worker ml-dev-ui
```

Open **http://127.0.0.1:8002**. Change `ML_DEV_UI_PORT` if needed.

1. Upload a JPEG/PNG/WebP or MP4/MOV/WebM/Matroska file, or index downloaded samples.
2. Watch job state and attempts update automatically every two seconds.
3. Search in natural language. View matching images or play videos from the
   returned frame time. Raw search JSON is available in an expandable panel.
4. Reindex an asset or remove its embeddings. Removal keeps its original file;
   active jobs must finish first. Failed jobs can be requeued with Retry.
5. Use **Test a failed job & retry** to queue a missing image that is restored
   after its first failure. With default retry settings it succeeds on attempt 2.

The UI gateway stores uploads in ignored `data/media/`, registers UUIDs only in
the guarded local fixture, and enqueues work for the real background worker.
It proxies search to the actual ML API; it does not generate mock results or
load another model. Uploads are streamed and bounded by `ML_MEDIA_MAX_BYTES`.
The API/worker retain read-only media mounts; the development gateway can write
uploads and retry fixtures. Video previews use the browser's native codecs,
while indexing uses FFmpeg independently.

This console intentionally bypasses the future Spring Boot frontend flow for
local testing. It has no employee authentication or S3 access; keep the optional
service bound to localhost. `/dev/*` routes belong only to this separate test
app. It refuses production-style asset schemas. No production metadata migration
is added. Similar media remains future step 8.

Stop only the UI with:

```bash
docker compose --profile ui stop ml-dev-ui
```

Downloaded image/video credits remain in the evaluation manifests and attribution
files. Browser QA screenshots/reports are under ignored `outputs/`.
