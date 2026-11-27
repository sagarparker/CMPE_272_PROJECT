# Integrated MVP API contract

All browser application calls use Spring Boot under `/api`. Supply the
Keycloak access JWT as `Authorization: Bearer ...`. Validation checks signature,
issuer, audience, and expiry. Authorization uses current PostgreSQL roles.
New users have no roles. ADMIN does not imply UPLOADER or RESEARCHER.

Errors use `{"error":{"code":"...","message":"..."}}`. Anonymous/invalid/
expired sessions receive 401; missing permissions 403; missing resources 404;
invalid input 400; invalid lifecycle transitions 409; unavailable search 503.
Search dependency failures use `ML_SEARCH_UNAVAILABLE`; concurrency rejection
uses `ML_SEARCH_BUSY`, both HTTP 503. See the observability documents for the
99% SLO and the 1.5-second default downstream deadline.

## Identity and admin

| Route | Access | Response / behavior |
|---|---|---|
| GET `/api/me` | Authenticated | `{id,email,displayName,roles:[]}`; provisions account on first request |
| POST `/api/logout` | Authenticated | Revokes current API session; frontend also ends Keycloak session |
| GET `/api/admin/users` | ADMIN | Array of provisioned user profiles |
| PUT `/api/admin/users/{id}/roles` | ADMIN | `{roles:["UPLOADER","RESEARCHER"]}` replaces complete role set; audited |

The last administrator cannot be removed. Bootstrap uses one explicit issuer-
validated subject on first provisioning only. `sid` identifies provider sessions;
API sessions expire after 30 minutes idle or 8 hours absolute.

## Catalog and transfers

| Route | Access | Behavior |
|---|---|---|
| POST `/api/assets/initiate` | UPLOADER | Creates UPLOADING; returns `{assetId,uploadUrl,status}` |
| POST `/api/assets/{id}/complete` | UPLOADER + owner | 202; verifies private storage, sets PROCESSING, creates one job; repeat-safe |
| GET `/api/assets?offset=0` | UPLOADER | Up to 50 owned assets, newest first |
| GET `/api/assets/{id}` | Owner with UPLOADER, or RESEARCHER for READY | Asset metadata; no storage key |
| PUT `/api/assets/{id}` | UPLOADER + owner | Replaces editable metadata |
| POST `/api/assets/{id}/access-url?download=false` | RESEARCHER + READY | `{url,expiresInSeconds:60}`; preview/download issuance audited |
| POST `/api/assets/{id}/similar` | RESEARCHER + READY | Ranked related READY assets, excluding source |

Initiation example:

```json
{"filename":"elephants.mp4","contentType":"video/mp4","title":"Elephants at sunset","description":"Herd by a watering hole","species":"African elephant","location":"Botswana","capturedAt":"2025-08-14","contributor":"Field crew","usageNote":"Verify rights before publication"}
```

`mediaType` is optional (`image|video`) and must agree with `contentType` if
supplied. Accepted types: `image/jpeg`, `image/png`, `video/mp4`,
`video/quicktime`. PUT the file to `uploadUrl` with exactly that Content-Type
and `If-None-Match: *`, then call complete. The condition prevents overwrites.
PUT expiry is 15 minutes. Completion checks nonzero length up to 100,000,000
bytes and the stored media category; the worker validates decoding/video limits.
A signed PUT itself does not enforce a storage quota.

Asset metadata shape:

```json
{"assetId":"uuid","ownerId":"uuid","mediaType":"video","title":"Elephants at sunset","description":"Herd by a watering hole","species":"African elephant","location":"Botswana","capturedAt":"2025-08-14","contributor":"Field crew","usageNote":"Verify rights before publication","processingStatus":"READY"}
```

PUT metadata accepts `title`, `description`, `species`, `location`,
`capturedAt`, `contributor`, `usageNote`; title is required. FAILED assets
return 409 on completion; processing retries are owned by the worker.
Presigned GETs remain usable until expiry even if a role is revoked.

## Search

POST `/api/search` requires RESEARCHER:

```json
{"query":"elephants drinking at sunset","mediaType":"video","location":"Botswana","species":null,"capturedAfter":null,"limit":10}
```

Filters are optional. Location/species are case-insensitive substring matches;
`capturedAfter` is an inclusive date boundary. Limit defaults to 10, maximum
100. The query must also fit the selected embedding model's token budget
(77 for CLIP and 64 for the SigLIP 2 trial, including special tokens).

```json
{"results":[{"assetId":"uuid","title":"Elephants at sunset","mediaType":"video","score":0.83,"frameTimestampSeconds":72.0,"species":"African elephant","location":"Botswana","processingStatus":"READY"}]}
```

Spring selects eligible READY catalog IDs using the requested filters. In the
integrated Gemma stack, text search ranks all eligible indexed assets using
`0.80 * image cosine similarity + 0.20 * metadata cosine similarity`, then applies
the requested result limit. Gemma embeds the query with its SearchQuery prompt
and catalog text (title, description, species, location, generated visual description)
with its Document prompt.
Metadata vectors are cached by model version and a fingerprint of current text;
stale text vectors are excluded and refreshed on search. Empty metadata contributes
zero. For video, the image component uses the best matching sampled frame.

The local Gemma API additionally checks up to 20 shortlisted candidates against
their generated visual descriptions, rejecting unsupported query requirements.
Verification results are cached by query and caption. A failed verification
dependency returns 503 instead of silently returning unchecked candidates.

The API includes combined scores at or above `0.67`
(`ML_SEARCH_MIN_SIMILARITY`); lower scores are hidden. Related-image search
continues to use visual cosine similarity with the same cutoff. Scores express
ranking, not probabilities. If no eligible asset meets the cutoff, the API
returns `{"results":[]}` with HTTP 200.

## Internal Python and database handoff

Python has no host-facing port in the integrated stack. Internal search
accepts `{query,limit,assetIds?}` and returns `{matches:[{assetId,score,
frameTimestampSeconds}]}`. Internal similar accepts `{assetId,limit,assetIds?}`.
Only Spring supplies the eligible set for public requests. Standalone ML
fixtures can omit it. For MVP, the set is sent as UUIDs; large archives should
move filtered ranking into a database query rather than sending large sets.

The worker invokes shared `IndexingService.prepare_image/prepare_video`
functions directly. This is the agreed co-located embedding handoff; no
`/internal/embed-media` HTTP route is needed. Real CLIP weights/revision,
512-dimensional normalization, and timestamp validation remain unchanged.

Flyway creates `users`, `user_roles`, `audit_events`, `api_sessions` (V100),
`assets` and `index_jobs` (V200/V201), and `asset_vectors` (V300). Production
jobs use `media_reference=assets.s3_key`. Workers claim with `SKIP LOCKED`,
renew a token-bound lease, retry with bounded backoff, and atomically commit
vectors/SUCCEEDED/READY. Stale claims cannot finalize. The standalone `ml_dev`
schema remains isolated and is never used by the integrated backend.

### Provider-specific upload headers

`POST /api/assets/initiate` additionally returns `uploadHeaders`, a map the
browser includes in its PUT to `uploadUrl`. Azure requires
`x-ms-blob-type: BlockBlob`. Clients also send
`Content-Type` and `If-None-Match: *`. Azure upload SAS permits create only,
while preview/download SAS permits read only for 60 seconds. The API verifies
object size/type on completion; worker decoding limits still apply. Existing
`s3_key` database columns retain their historical names but hold opaque catalog
object keys, equally valid for a fresh Azure deployment. Do not switch providers
on a populated database without migrating its objects.


### Generated visual descriptions

The local upload worker generates a separate visual description during processing.
`GET /api/assets/{id}` includes nullable `generatedDescription` under the same
owner/researcher authorization as other metadata. Editable `description` remains
user-supplied; generated text is not accepted from metadata-edit requests.
Captions and vectors are committed with READY only by the current lease owner.
The text embedding fingerprint includes generatedDescription, so a new caption
invalidates any older cached metadata vector. Local generation requires Ollama
and the configured Gemma 4 vision model; transient failures use upload retries.
