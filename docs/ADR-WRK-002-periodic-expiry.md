# ADR-WRK-002: Periodic Owner Expiry Scan

Status: accepted for this increment; HU-WRK-001 remains open.

## Decision

ASGI lifespan owns one sequential task per process. When explicitly enabled, it
scans at startup, then waits the configured interval after success or failure.
No inbound event is necessary. It enumerates /api/v1/stock with page/limit=100,
which permits the existing INVENTORY Worker identity. Only canonical lotId is
consumed; dates/balances stay authoritative in Inventory's evaluation transaction.
Each HTTP request rereads the exclusive token and carries one trace per pass.
No SQL, private signing key, public trigger endpoint or new dependency is added.

Strict page metadata/length/identities prevent malformed partial pages being treated
as complete. IDs are deduplicated within a pass. The page cap fails explicitly;
datasets beyond it require operator adjustment rather than claiming full coverage.
Expired and zero-stock lots are included so existing alert evidence can resolve.
Any owner error stops the attempt; the next interval restarts at page one. Restart
also restarts at page one, relying on stable owner alert identity, not local state.
Multiple processes may repeat scans; owner row locks/unique lot alerts serialize
effects. There is no cluster-wide singleton or exactly-once scheduling claim.

Stock count/page share their owner's per-request snapshot, not one snapshot across
the pass. Concurrent insertions can shift offsets: COMPLETE means traversal of the
pages returned, not an atomic global census. Subsequent passes revisit the dataset;
continuous churn does not provide a strict coverage deadline. Keyset enumeration
would be a follow-up for that stronger requirement.

Health separates RUNNING/COMPLETE/FAILED/DISABLED from process UP. A failed attempt
has no evaluated count and preserves lastCompletedAt of the preceding success.
Shutdown requests cooperative stop between calls/lots and waits the current HTTP
operation; the existing five-second HTTP timeout is not a hard pass deadline.
Credentials still require existing Security issuance/renewal; expired tokens fail
scans until renewed. Scan, event-expiry and low-stock flags are distinct; scans
cannot be enabled while expiry is disabled. No live flag or credential is changed.

## Verification

Python 3.12 tests exercise multi-page/deduplicated enumeration, empty/full last
pages, malformed pages, failures, cap, cancellation, startup/retry/disabled lifespan
and signed Worker HTTP without events. Lifecycle tests accelerate the wait in the
helper; deployed settings enforce the 60-second minimum.
Docker acceptance enables startup scanning and checks a completed evaluation before
any relay event, followed by the existing event/replay/renewal checks. Credentials
are synthetic and Inventory is a stub: not real SQL, civil-midnight classification
or production acceptance. Inventory's native owner tests cover its own date rules.
Live schema alignment, real signed pipeline, Gateway/front and QA remain pending.
