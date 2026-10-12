# ADR-WRK-001: Event-Triggered Owner Expiry Evaluation

Status: accepted for this increment; HU-WRK-001 remains open.

## Decision

With WORKER_EXPIRY_ENABLED=true, consume validates Inventory's event receipt before
requesting POST /api/v1/internal/alerts/expiry/evaluate. The body is only lotId and
configured windowDays (1..365, default 30). Dates, physical stock and persistence
belong to Inventory. The event's stock/date snapshot is never used for evaluation.
Both requests authenticate as mis-worker/INVENTORY with the exclusive subject and
carry the original event trace. Each request rereads and validates the token file.
The default flag is false; malformed flags/windows fail startup rather than coerce.

Evaluation also runs after applied=false: the first owner commit can succeed before
evaluation fails or the process stops. A relay retry must repair that gap, not skip
the alert because inbox already holds the event. Two owner transactions are not an
atomic distributed transaction. Worker has no persistent queue or database access.
No relay acceptance is returned unless both owner receipt and evaluation validate.
Non-200/timeouts yield 503; malformed receipts yield 502. Relay owns retry policy.
Evaluations refresh current owner state, not the immutable event response snapshot.
Resolved records remain valid evidence; false/null means no record, not an error.

The response schema is derived from Inventory API OpenAPI at e7996f1 (develop merge
cebf49f), ExpiryEvaluation/ExpiryAlert components. Strict shape, date formats,
lot identity, integer balance and configured horizon are checked without redoing
the owner's classification. Later contract changes must update both publications.

## Acceptance And Limits

2026-10-12: Python 3.12 unit suite covers signed relay/Worker identities, failures,
replay repair, response contracts, settings and token renewal between the two calls.
Docker acceptance enables expiry on a private UID-10001 Worker with read-only root,
no capabilities/host ports and synthetic credentials. The owner stub validates
signed Worker requests and records event -> evaluation order, duplicate events,
correlation and renewed credentials. The isolated project is removed afterward.
These checks are transport evidence, not real Inventory SQL or end-to-end acceptance.
The Inventory evaluator's native persistence evidence is in its own repository.

Deploy only after Inventory has the HTTP increment and seven DB changesets. No live
schema/container/credential is changed here. Event-only evaluation misses lots that
become expired without a new movement and historical lots without new events.
Periodic owner enumeration, scheduling, catch-up, real signed pipeline, Gateway,
frontend and QA are still required. Low-stock remains disabled and separate.
