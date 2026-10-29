# INTEGRATION-01: reviewed training handoff (mock only)

Baseline: database PR #2 at f72a7a1. Separate integration branch; no lesson-agent PR dependency. This adds a standalone FastAPI factory, not a route in main.py. No video, MediaPipe, model inference, OCR, external API, evaluation generation or deployment is performed.

## HTTP contract

- `POST /api/v1/reviewed-training-results/import`
  - JSON: [request schema](reviewed-training-import-v01.request.schema.json).
  - Required `Idempotency-Key` header: UUID.
  - Returns [import response](reviewed-training-import-v01.response.schema.json).
- `GET /api/v1/training-sessions/{training_session_id}/reviewed-training-results?analysis_run_id=<UUID>&limit=50&cursor=<UUID>`
  - Limit 1–100; stable UUID cursor, null when done.
  - Returns [page schema](reviewed-training-import-v01.query-response.schema.json).
- [OpenAPI](reviewed-training-import-v01.openapi.json), also exposed by the factory at `/openapi.json`.
- All successful result responses use `Cache-Control: no-store`; no untrusted source notes or reviewer aliases are returned.

Actual synthetic request/response captured from the in-process HTTP + PostgreSQL tests:
[request](reviewed-training-import-v01.example-request.json), [response](reviewed-training-import-v01.example-response.json).
These IDs belong to the disposable test run, not a deployed service. Requests are normalized before matching the trusted manifest; optional defaults, timezone representation and JSON object key order do not change the meaning. Exact numeric values survive parsing/storage/output with no float round trip.

### Required fields and V4/V5 mapping

| Contract | Existing source / purpose |
|---|---|
| `schema_version` | Literal `reviewed-training-import-v1` |
| `class_id`, `lesson_id`, `training_session_id` | Existing mock records; must belong to the authenticated tenant and to each other |
| `analysis_run_id` | UUID of the pre-registered synthetic analysis run; no new analysis task is started |
| `data_domain`, `time_unit` | Literals `mock`, `ms`; no unit inference/conversion or pilot fallback |
| `source.kind/is_mock/artifact_id` | `synthetic`, boolean true and a server-registered artifact UUID; labels alone are insufficient |
| `source.source_stream_id` | Stable upstream review-history stream UUID |
| `events[].event_id` | V5 legacy ID `evt_` + 12 lowercase hex digits; never a free-text statement |
| `feature`, frames, times, deviation | V4 six scalar fields; all must equal the original snapshot |
| `original_event` | Six required values, optional V4 duration/n_frames/swing. Ordered intervals; optional duration agrees at V4 three-decimal precision and frame count agrees with inclusive range |
| `review.review_status` | Original V5 five-state meaning, not a technical-error classification |
| `review.review_history[]` | Original array order becomes explicit sequence 1…N; status, MOCK reviewer reference, timezone-aware time, note |

Native V5 JSON has no sequence field; a future adapter may number its existing history in array order, but must not invent history or authenticate a reviewer string. The wrapper `{review: ..., demo: ...}` from V5.2 is not accepted directly. Use the published normalized contract. No raw video, URL, face identity, student name or health fields are accepted.

All numbers must be JSON numbers, finite, nonnegative, <=1e12, at most 80 digits / 60 fractional places. These are interchange/resource bounds, not medical or technical performance thresholds. Frames are strict nonnegative integers. Missing/contradictory values, invalid IDs, false mock markers, unexpected fields, duplicate JSON keys, malformed UTC conversion and oversized bodies fail. A unit tag cannot prove the physical time unit; the trusted synthetic manifest must have correct units.

## Trust boundary: receipt is not human approval

Every incoming review is persisted only as `imported_unverified`. Its source status, sequence and time are preserved in the separate intake schema. All source notes are marked `quarantined`, including apparently benign notes. Notes never enter response/evidence text; readers/importers cannot SELECT the raw-note column. Control characters in notes are rejected.

Neither a source status `confirmed`, nor the source's `reviewed_by`, nor a self-reported role/tenant/authenticated flag grants human trust. `confirmed` means observable movement change, never an automatically confirmed technical error. No source claim is written into `teaching.coach_reviews`.

The query overlays the existing authoritative `teaching.event_review_state`. Only decisions created by the existing authenticated coach database function count as `authenticated`. Pending/tracking_error/uncertain and quarantined events are excluded from observation-summary eligibility. Confirmed/normal_movement may support a neutral observation summary after trusted human review, **not** automatic technical diagnosis, scoring or exercise prescription. Technical error assessment always remains `not_assessed`. Empty results do not imply good performance.

`data_received=true` means the import transaction committed. `upstream_reviews_authenticated=false` remains explicit even if an event separately has a trusted database review. Summary counts describe only the returned page.

## Caller identity and source provenance

Use `create_app(identity_provider=...)`. The provider is a synchronous **server-side** authentication adapter returning frozen `TrustedIdentity(tenant_id, db_login, engine)`. It must validate a real server session/token/mTLS identity before choosing a tenant-scoped engine. Do not build it from body fields or self-reported X-Role/X-Tenant headers. The default factory has no provider and returns 401; it never connects to a database automatically. No pretend Coze/JWT authentication is shipped.

The service compares context tenant/login against the real PostgreSQL `session_user` and `teaching.current_tenant()`. POST requires a dedicated restricted login `tdb_<tenant hex>_importer`, granted only the new NOLOGIN group `teaching_importer`. The role can execute the controlled import function, but cannot directly insert events, receipts, claims, manifests or human reviews. Ordinary `teaching_agent` is not granted this function. GET can use a separately authenticated `teaching_reader` engine. Migration/admin engines fail the context binding and must never be application credentials.

Trusted synthetic provenance is enforced independently in the database: a fixture administrator pre-registers the exact normalized payload in private `teaching_ingest.mock_artifacts`. No public registration endpoint or business-role write grant exists. The import function requires an exact same-tenant manifest match. A request cannot relabel a real Coze result as mock merely by changing its flags. The trust of this registry still depends on the administrator admitting only genuinely synthetic artifacts; source authenticity cannot be inferred from coordinates alone.

The current implementation deliberately does **not** ingest real Coze results, verify Coze signatures or authenticate upstream humans. A future real-data pilot needs separate approval, domain support and a trusted review attestation protocol; do not weaken the mock manifest gate to make a real payload pass.

## Persistence and replay rules

Migration `0003_training_import` adds **three intake tables in teaching_ingest**, leaving the original six business tables and existing immutable-event checks unchanged:

- `mock_artifacts`: private, immutable canonical synthetic source manifests.
- `receipts`: immutable requests, tenant-scoped idempotency key, bindings and event-ID mapping.
- `review_claims`: immutable unverified history, unique by event + source stream + sequence; authenticated is forbidden by CHECK.

All enable and FORCE RLS. `teaching.current_tenant()` is extended to recognize dedicated `_importer` logins; existing roles keep their boundaries. Original migrations 0001 and 0002 are untouched.

The controlled function locks the training session, resolves/deduplicates candidate events using existing scoped unique keys, then writes receipt and claims in one transaction. Any conflict rolls back the entire batch.

- Same key + same manifest: same receipt, `replayed=true`; result summary reflects current database review state.
- Same key + different registered manifest: 409, no partial writes.
- Different key + same source facts/history: a new receipt is allowed, but event/history rows are reused.
- Same source sequence with changed status/reviewer/time/note: 409, no overwrite.
- New source history must be contiguous and append compatible with prior claims; new submissions cannot truncate history. Exact replay of a previously accepted key remains allowed.
- Existing event with the same legacy ID or span but different source facts/snapshot: 409.

Error classes: 401 missing identity; 403 identity/provenance/permission failure; 404 unavailable tenant-scoped session/binding; 409 replay/history/event conflict; 413 body >1 MiB; 422 schema or database contract failure; 503 storage unavailable. Error responses do not return SQL, credentials or input values.

## Local verification, no deployment

Use the existing DB-A disposable PostgreSQL 16 safety settings; never use PGDATABASE_URL or the production database factory:

```bash
# Securely supply TEACHING_DATABASE_URL for loopback :55432/coachloop_db_a_test.
export TEACHING_ALLOW_MIGRATION=mock-only
.venv/bin/python -B -m alembic -c teaching_alembic.ini upgrade head
.venv/bin/python -B -m pytest -q -p no:cacheprovider
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/teaching/test_training_import.py
```

The test harness rebuilds only the explicitly opted-in disposable database and provisions real restricted roles. The integration tests register synthetic manifests with the isolated migration administrator, then send requests through FastAPI TestClient under the importer login; this is not a superuser substitute for RLS testing. Optional INTEGRATION_EXAMPLE_DIR captures synthetic request/response examples outside the repository.

Downgrade drops only the new intake schema and restores the previous tenant parser; it retains the NOLOGIN group as security provisioning. It does not remove or modify original events or authenticated coach history. Dropping this revision loses intake receipts/unverified claims, so only use downgrade in the disposable mock environment.

## Coze handoff still needed / explicit limits

Supply the published video node's actual output schema and a synthetic success/failure sample, its job/run IDs, frame/time conventions, review history format and service authentication method (configuration names only, never secrets). Map outputs to this contract without calling MediaPipe again. Current HTTP calls were in-process only; no Coze endpoint or public service was contacted or deployed.

Not implemented: real data admission, source/human signature verification, a registry administration UI, Coze plugin registration, production authentication adapters, per-class authorization, global report metrics, post-class evaluation generation, teacher re-review of evaluations, or evaluation/report archive tables. All source claims remain untrusted until a separate verified human workflow acts through the existing database mechanism. This task stops at data handoff; it does not start the next project.

## Acceptance evidence

Isolated PostgreSQL 16.15: **190 passed, 0 failed, 0 skipped** (the retained database/video baseline of 140 plus 50 HTTP/PostgreSQL integration cases). Original V2–V5.2 suite separately: **41 passed**. Head revision: `0003_training_import`. No external Coze/video/model API was called. Schema upgrades, full downgrade/re-upgrade and populated legacy database upgrades remain covered by the retained migration tests.
