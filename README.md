# mis-worker

> Asynchronous jobs and background processing

Part of the **Medicine Inventory System** distributed system — team `medicine-inventory-system`, Grupo 1.
Governance and documentation live in [`mis-docs`](https://github.com/code-corhuila/mis-docs).

## Branching

Three permanent branches. **None of them accepts a direct commit** — you enter through a child
branch and leave through a Pull Request.

```
develop  <--PR--  feat/... fix/... chore/...
qa       <--PR--  qa/...
main     <--PR--  release/...  hotfix/...
```

Promotion happens **by re-application** (`git cherry-pick -x`), never by merging one permanent
branch into another: `merge develop -> qa` and `merge qa -> main` do not exist in this model.

`main` requires **1 approval from `ariel5253`**. On `develop` and `qa` the team sets its own review
rule.

Full policy: `00-governance/branching-policy.md` in `mis-docs`.

## Stock Event Consumer Core

Python 3.12 with jsonschema validates Inventory v1 stock events, strict scalar types,
canonical identities and delta consistency. It returns acknowledgement only after
the owner effect port confirms the same event. Worker never stores or alters stock.
Run `python -m pip install -r requirements.txt` then `python -m unittest discover -s tests -v`.
The core suite uses a fake owner. Authenticated ASGI transport and its signed
credential tests are described in docs/ADR-EVT-002-authenticated-transport.md.
Durable inbox/effects belong to Inventory. Worker deployment is described below;
live relay activation and full acceptance remain pending. HU-EVT-001 is not closed
by the transport unit suite.

## Private Container

deploy/compose.yml adds Worker to the platform with no host port or database.
Required configuration and credential mounts are documented in
docs/ADR-EVT-003-private-worker-deployment.md. With Docker available, run
`python tests/check_deployment.py` to verify container HTTP using synthetic
credentials and an owner stub. This does not deploy the live Inventory relay.

## Event-Triggered Expiry Evaluation

WORKER_EXPIRY_ENABLED=false by default; WORKER_EXPIRY_WINDOW_DAYS=30 (integer 1..365).
When enabled, each valid owner receipt, including applied=false replays, is followed
by owner HTTP evaluation of that lot before the relay acknowledgement. Worker sends
only lotId/windowDays, never client balances/dates, and keeps no alert state or SQL.
Inventory API must include the expiry HTTP increment and all seven DB changesets
before enabling this flag; no live environment is enabled by this publication.
See [decision and acceptance](docs/ADR-WRK-001-event-triggered-expiry.md).
Periodic scans are now implemented separately as described below; live activation,
Gateway/front and QA remain pending. HU-WRK-001 is not closed. This flag is unrelated
to disabled low-stock work.

## Periodic Expiry Scan

WORKER_EXPIRY_SCAN_ENABLED=false by default and requires WORKER_EXPIRY_ENABLED=true.
When enabled, ASGI lifespan scans immediately, then waits 900 seconds after each
attempt (WORKER_EXPIRY_INTERVAL_SECONDS, integer 60..86400). It enumerates owned
lot IDs through authenticated GET /api/v1/stock, 100 rows per page, evaluating each
through the existing owner endpoint. This includes old, expired and zero-stock lots.
WORKER_EXPIRY_MAX_PAGES defaults to 100 (1..1000); hitting the cap marks the attempt
FAILED, not complete. Increase this bound if the dataset exceeds 10,000 lots.
Health's expiryScan exposes status, attempts, evaluated count and lastCompletedAt;
top-level UP is process liveness, not successful alert refresh. No durable scan
checkpoint or frozen cross-page snapshot is claimed. See
[decision and acceptance](docs/ADR-WRK-002-periodic-expiry.md).
