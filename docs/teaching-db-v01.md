# Teaching DB V0.1 — DB-A

Independent, PostgreSQL-only, mock-only persistence. Based on main e5448e8; no dependency on the unmerged lesson-agent PR. No legacy database factory, service startup, video code, OCR, real records or external API is used.

## Layout and boundaries

- `src/storage/teaching/models.py`: independent SQLAlchemy metadata, six business tables in `teaching`.
- `teaching_alembic.ini`, `teaching_migrations/`: independent, frozen SQL revision. Public `teaching_alembic_version` is migration metadata, not a seventh business table.
- `src/storage/teaching/mock_data.py`: entirely synthetic six-table chain using separately authenticated engines.
- `tests/teaching/`: offline checks and real PostgreSQL integration tests.

Relationships: classes → lessons → lesson_plans; lessons → training_sessions → pose_events → coach_reviews. Sessions optionally reference a plan **of the same lesson**. Every FK includes tenant and data domain. Plan versions are immutable; version allocation locks the lesson. Event snapshots and review actions cannot be updated/deleted, including through ordinary owner DML. Downgrade intentionally drops teaching data, so it is restricted to explicit mock/test databases.

All six tables CHECK `data_domain = 'mock'`. `pilot` cannot be inserted, even by a migration administrator using ordinary INSERT. Raw videos and feature files are not loaded: only distinct `mock://videos/…` and `mock://features/…` references are supported. Participants use `MOCK-…` codes. No student/name/health table exists. Arbitrary free text is not a DLP mechanism: never put personal data in notes, payloads or provenance.

DB-A is a minimal subset of the earlier design: no legacy JSON importer, identity mapping, knowledge-evidence certification, real media access, production auth integration or per-class authorization yet. `db-a-1` is an independent payload shape, **not** the PR #1 Pydantic serialization. Do not import the PR payload as trusted data or silently rewrite it. Those adapters and additional governance belong to a later, separately authorized phase.

## Constraints and business semantics

- Standard mode: lesson and plan total=45; prep 8–10, main 28–30, closing 5–7, sum=45; load total=45. Unsupported template/level rejected on lessons.
- Payload has seven non-empty object elements. Its time/load input fields must match the scalar columns. Missing, malformed and mismatched data are rejected by PostgreSQL.
- NUMERIC inputs retain precision. Group and individual density are database-generated expressions, never client-provided results. Labels are derived from `measurement_kind` (`estimated` / `measured`), not stored separately. Heart rate 20–250 is a broad ingestion validity domain, **not** a medical safety or exercise target.
- Plan state: draft → pending → approved / needs_revision. New content needs a new version. Review history appends state, sequence, authenticated actor, time and note.
- Event state defaults to pending in the security-invoker view. Coach actions allow pending / confirmed / normal_movement / tracking_error / uncertain. `confirmed` means confirmed observable movement change, **never** an automatically confirmed technical error.
- Human reviewers come from `session_user`; client-supplied reviewer names are not accepted. Concurrent reviews require the expected sequence; stale writes raise SQLSTATE 40001. Idempotency keys return the same result only for the same actor/event/status/note.

## Authentication and minimum permissions

DB-A uses dedicated database logins, provisioned by the migration administrator:

`tdb_<tenant UUID as 32 lowercase hexadecimal characters>_<agent|teacher|coach|reader>`

Grant exactly one matching NOLOGIN group: `teaching_agent`, `teaching_teacher`, `teaching_coach`, `teaching_reader`. Logins must have NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOBYPASSRLS and no memberships in other tenants' roles. Role names encode a trusted administrator-issued identity binding; a caller cannot create its own LOGIN or change `session_user`. Do **not** use a shared privileged account or SET ROLE as a substitute for authenticated login.

| Group | Read | Write |
|---|---|---|
| agent | Own tenant/mock rows | `create_draft`; submit own tenant draft to pending through `review_plan` |
| teacher | Own tenant/mock rows | INSERT classes/lessons/sessions/events; create drafts; teacher decisions through `review_plan` |
| coach | Own tenant/mock rows | Append actions through `review_event` |
| reader | Own tenant/mock rows | None |

No business group gets direct INSERT/UPDATE/DELETE on coach_reviews or direct DML on lesson_plans. All tables enable and FORCE RLS. The view uses `security_invoker=true` (PostgreSQL >=15). Tenant identity is derived from the authenticated `session_user`, never a client-controlled GUC. SECURITY DEFINER functions fix their search_path, check caller membership and explicitly scope all row lookups. PUBLIC has no schema/table/function grants. Migration admins remain trusted, powerful principals, never application credentials.

Group roles are cluster-level security provisioning. Downgrade retains them and their LOGIN memberships; it does not remove principals that could be used elsewhere. Fresh upgrades refuse group roles with unsafe attributes or inherited roles. Do not retrofit these roles into an unknown shared cluster without a separate access review.

## Reproduce in a disposable PostgreSQL database

Use an isolated PostgreSQL >=15 instance with no production mounts or data. For integration tests the safety guard additionally requires `127.0.0.1` / `localhost`, port **55432**, database **coachloop_db_a_test**. Tests rebuild the `teaching` schema via upgrade → downgrade → upgrade, then provision randomized authenticated logins. Never point these tests at an existing business database. Use a cluster administrator only for this isolated test harness.

Set secrets in the local process or a protected file outside the checkout; never commit passwords or dump the environment:

```bash
export TEACHING_DATABASE_URL='postgresql+psycopg://<test-admin>:<test-password>@127.0.0.1:55432/coachloop_db_a_test'
export TEACHING_ALLOW_MIGRATION=mock-only
.venv/bin/python -B -m alembic -c teaching_alembic.ini upgrade head
.venv/bin/python -B -m alembic -c teaching_alembic.ini current
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/teaching
.venv/bin/python -B -m pytest -q -p no:cacheprovider
```

Migration requires PostgreSQL and an explicitly supplied `*_mock` / `*_test` database. It never reads `PGDATABASE_URL`, Coze identity, legacy `.env` or SDK credentials. Missing TEACHING_DATABASE_URL makes integration tests **skip**, not pass; offline checks alone do not establish PostgreSQL/RLS readiness. No SQLite fallback exists.

To exercise mock seeding outside pytest, provision three tenant-bound LOGINs as above and call `seed_mock_chain(teacher_engine, agent_engine, coach_engine, tenant_uuid)` with SQLAlchemy engines authenticated separately. The helper does not open engines, read environment variables or contact the legacy database. It returns the six row IDs. All records are synthetic, including the simulated approval; they are not approved real teaching instructions.

## Verified DB-A scope

Tests cover actual migration round-trip, table/model alignment, all composite child FKs, mock-only CHECKs on every table, RLS reads across every table and the view, spoofed GUCs, cross-tenant function calls, direct approval/reviewer forgery, append-only triggers, stale/concurrent review writes, idempotency, plan version allocation, invalid phases/load/status, generated-density tampering and transaction rollback. Existing V2–V5.2 tests run unchanged.

Not production-ready: tenant LOGIN provisioning and secret lifecycle remain administrator-managed; same-tenant per-class permissions, school authentication, retention/deletion workflow, production audit export, PR #1 evidence/output repairs and real JSON import are not implemented in DB-A. Do not enable pilot or auto-start DB-B.

## Initial DB-A acceptance result (903fc6a)

PostgreSQL 16 disposable instance, no production data: full suite **90 passed** (41 unchanged main/V2–V5.2 tests + 49 DB-A tests: 46 PostgreSQL integration and 3 offline). Migration round-trip and revision `0001_teaching` verified. No dependency declarations, lockfiles, main.py, graph or existing video modules changed.


## PR #2 targeted snapshot consistency fix

Revision `0002_event_snapshot` replaces only the event snapshot CHECK; revision 0001 SQL and all RLS/permission/history definitions remain unchanged. The ORM and migration use identical frozen expressions. `feature`, `frame_start`, `frame_end`, `start_time_ms`, `end_time_ms`, and `deviation_max` must be present and match their scalar columns. Feature must be a JSON string, numeric evidence must be JSON numbers, and frame tokens must be nonnegative integers (retaining the old integer-token compatibility for downgrade). Equality uses NUMERIC without tolerance, so a small discrepancy is rejected too.

A missing, null, malformed or contradictory value raises a database CHECK violation even for a directly authenticated, non-superuser teacher INSERT. Matching decimal values preserve precision. Prior fixtures that omitted time/deviation values now include the complete synthetic snapshot; no existing test was removed.

Upgrade validates existing rows transactionally. If any legacy snapshot is missing or contradictory, the upgrade aborts, retaining revision 0001, its original CHECK and all original data. It never fills missing evidence from scalar columns or silently edits immutable snapshots. Such data requires separate source verification and an explicitly authorized remediation plan before retrying. Downgrade restores the former weaker CHECK without rewriting records; it is not a safety-preserving way to retain the fix.

Validation covers fresh upgrade → base downgrade → head upgrade, populated 0001 → 0002 → 0001 → 0002, and rollback on incomplete/conflicting legacy evidence. All old permission, RLS, concurrency, idempotency and history tests remain enabled. This change does not enable pilot or connect to production.

Targeted fix acceptance on isolated PostgreSQL 16.15: **140 pytest tests passed** (the retained 90 plus 50 new cases), no failures/skips. The previous independent review's unchanged 10 temporary probes also passed, including the formerly failing restricted-teacher snapshot INSERT. Current revision: `0002_event_snapshot`.
