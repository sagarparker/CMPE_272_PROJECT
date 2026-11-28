# How MediaMesh works

This guide describes the current integrated application in `compose.yaml`.
The current Mermaid diagrams are embedded in the [root README](../../README.md#system-architecture).
The existing SVG/PNG are historical deployment illustrations; use the README as
the current source of truth. The separate
[Azure deployment reference](azure-deployment-architecture.html) describes the
older cloud manifest and explicitly identifies the search parity gap.

## Responsibilities

| Component | Responsibility |
|---|---|
| React + nginx | Login redirects, upload forms, Explore phrases, search and media previews |
| Keycloak | OIDC authorization code + PKCE, login sessions; production realm adds password rotation/TOTP |
| Spring Boot | JWT signature/issuer/audience/expiry validation, current DB roles, catalog, jobs, signed media access |
| Blob Storage / Azurite | Private original files and derived browser-compatible video playback copies |
| PostgreSQL + pgvector | Assets, users, roles, sessions, jobs, captions, image/frame vectors and cached text vectors |
| ML worker | Lease one queued job, read media, sample video frames, call embedding/caption models, commit READY |
| Shared EmbeddingGemma 2 | Create 768-dimensional image, frame, query and document embeddings locally |
| ML API | Refresh text vectors, retrieve and rank eligible assets, verify shortlisted captions |
| OpenRouter Gemma 4 | Generate captions from pixels on upload; check saved text captions during search |
| Prometheus | Scrape backend metrics; it is not part of ranking or model inference |

## Upload to searchable asset

1. The browser requests an upload from Spring Boot with an access JWT. The API
   checks UPLOADER and creates an `UPLOADING` record containing the owner,
   metadata and object key.
2. The API returns a short-lived create-only Blob SAS. The browser uploads the
   bytes directly to private storage, then calls the completion endpoint.
3. The API checks ownership and the stored object's size/type. In one database
   transaction it marks the asset `PROCESSING` and creates a retryable job.
4. The worker claims a job and renews its lease while processing. For an image it
   creates one visual embedding; for a video FFmpeg samples bounded frames and
   each frame receives a vector plus its timestamp. A playback copy is optional;
   failure to create it can fall back to the original for preview.
5. The worker sends a bounded JPEG, or up to three sampled frames, to OpenRouter
   for a factual description. Authored metadata is kept separately.
6. The current lease owner atomically saves the visual vectors, generated caption,
   caption model and `READY` status. Transient failures retry; exhausted or invalid
   jobs become `FAILED`. Browser login expiry does not stop an already queued job.

Indexing means creating these searchable representations, not merely uploading
bytes. It does not train or fine-tune either model. Video search understands
sampled frames; it does not transcribe audio or observe every video moment.

## Query to ranked results

The backend checks RESEARCHER and applies media-type, species, location and date
filters to READY assets. It sends the query and eligible IDs to the private ML
API; the browser cannot call that service directly.

EmbeddingGemma 2 encodes the query. The ML API also checks each eligible asset's
metadata-text fingerprint. Missing/outdated text embeddings are refreshed from:

```text
title + authored description + species + location + generated visual description
```

The fingerprint is a change detector, not a semantic score. Unchanged text reuses
its cached vector. An edit updates the text vector on search without reprocessing
image pixels; the seed also prepares this cache explicitly.

For each asset, pgvector computes:

```text
V = cosine(query vector, image vector)
    or the highest cosine score among the video's sampled frames
T = cosine(query vector, metadata-text vector)
S = 0.80 × V + 0.20 × T
```

Vectors must use the same embedding model/version and compatible preprocessing.
All three vector types use the same EmbeddingGemma 2 space. The SQL cosine
operator returns distance, so the implementation uses `1 - (embedding <=> query)`.
The metadata join checks both model version and the current text fingerprint;
missing valid metadata contributes zero. The database picks the best visual
frame before applying the 80/20 asset score, then sorts and limits the candidates.

An image score of 0.80 and text score of 0.60 give `S = 0.76`. The displayed 76
similarity is not a confidence percentage. The integrated default threshold is
0.67, checked by the verifier and again by Spring Boot. Related-media search is
visual-only and does not use the 80/20 combination or caption verifier.

## Final caption verification

OpenRouter receives the query and the saved descriptions of shortlisted assets
above the cutoff, in a bounded batch of at most 20. It returns supported indexes.
It does not receive image pixels in this step. Accepted results retain their
scores/order; rejected candidates disappear. The final stage is a filter, not a
third cosine score or an extra score weight.

The existing check asks for all explicit requirements, with a prerequisite for
positive color words. It can reject a true match if its caption omits a detail.
It can also make model mistakes. It is not proof of the contents of an image.
Results below the cosine cutoff never reach it. A large result count is not
ensured: the collection, filters, cutoff and final verification all affect recall.

Decisions are cached in memory by normalized query and full caption. Identical
repeats reuse those decisions; changing a caption or restarting the API causes a
new check. Only uncached candidates are sent, so batch composition can vary.
Timeouts or malformed output return search-unavailable; unchecked results are
not substituted. The local stack allows 30 seconds for verification, 40 seconds
for the backend ML request and 45 seconds for the browser search request.

## Preview, identity and credentials

The backend rechecks access before issuing a short-lived read SAS. The browser
fetches media directly from Blob Storage. Video results carry an approximate
best-frame timestamp. Signed URLs expire independently of later role changes.

Keycloak authenticates people; Spring Boot authorizes actions using current DB
roles. Tokens stay in browser memory. The frontend inactivity timer is separate
from backend request activity: periodic `/me` polling counts as backend activity,
so it is not independent proof of human inactivity.

The OpenRouter key is server-side, in ignored local `.env` or private deployment
configuration. It goes only to ML API/worker containers. `.env.example` contains
placeholders. Azure Blob access uses managed identity in the cloud; Azurite uses
public emulator fixtures locally. OpenRouter receives media samples for captions
and caption/query text for verification; embeddings are not sent to OpenRouter.

## Startup, seed and persistence

`./infra/manage.sh start` starts services and initializes schema/login fixtures;
it does not upload the demo media. The administrator's **Seed** tab asks the
backend to download the pinned demo images, write them to the configured storage
and queue normal indexing jobs; reruns resume and skip existing images. Existing
captions are retained across model changes.

Postgres, blob files and model weights persist in Docker volumes across normal
restarts. No caption or
embedding is regenerated on each normal search unless its cached text is stale.

## Runtime profiles and deployment parity

| Profile | Embeddings | Captions | Search verification |
|---|---|---|---|
| Root `compose.yaml` | Shared EmbeddingGemma 2, 768 dimensions | OpenRouter Gemma 4 by default | 80/20 hybrid + batch caption filter |
| Standalone `ml-service/compose.yaml` | CLIP by default | Disabled by default | Visual cosine baseline/dev harness |
| Current `compose.deploy.yaml` | CLIP default, loaded separately by API/worker | OpenRouter configured for new uploads | Visual cosine; no shared Gemma service or hybrid wiring yet |

The deployment manifest is a separate profile, not an overlay of the root file.
Adding the key alone does not enable hybrid search there. Before claiming Azure
parity, add the shared embedding service and version/configuration, enable
verification, adjust deadlines, reindex the deployed catalog and perform live
Azure acceptance checks. This documentation update does not deploy or migrate it.

Sources: [retrieval SQL](../../ml-service/src/mediamesh_ml/vectors.py),
[search orchestration](../../ml-service/src/mediamesh_ml/search.py),
[worker](../../ml-service/src/mediamesh_ml/worker.py),
[verifier](../../ml-service/src/mediamesh_ml/verification.py),
[hosted client](../../ml-service/src/mediamesh_ml/openrouter.py).
