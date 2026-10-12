# ADR-EVT-002: authenticated owner-confirmed HTTP transport

Status: accepted; container integration and relay remain pending.

Worker exposes POST /internal/events/stock-changed only for Security-issued
mis-inventory-relay JWTs: RS256, configured kid/public key, mis-events audience,
configured canonical subject, environment and no roles. Human or other service
identities are rejected. JWTs require iat/exp/jti, expire without grace and have
a 60..3600 second lifetime. Public keys are operator-provisioned, not taken
from token headers. No private key belongs in Worker.

Incoming JSON is streamed with a 64 KiB limit, then validated by the existing
event core. Worker sends the immutable event to the configured Inventory
origin at /api/v1/internal/events/stock-changed. It reads its token file on
each call, validates its own mis-worker/mis-api/INVENTORY identity and forwards
the event trace ID. The synchronous owner call runs outside the ASGI event
loop, with five-second network timeouts, no redirects or proxy environment.

Only an HTTP 200 owner receipt with the same event ID, integer sequence and
boolean applied produces accepted=true. Duplicate/stale receipts are accepted
because Inventory owns atomic deduplication. Invalid receipts return 502;
network/credential/non-200 owner failures return 503, never an acknowledgement.
Worker performs one attempt; the future durable Inventory relay owns retries.
Inventory remains the sole inbox/checkpoint/effect owner, not Worker.

Required environment variables (no credential defaults): WORKER_PUBLIC_KEY,
WORKER_TOKEN_FILE, WORKER_KEY_ID, WORKER_ENVIRONMENT, RELAY_SERVICE_SUBJECT,
WORKER_SERVICE_SUBJECT, INVENTORY_ORIGIN. Start with:
`uvicorn worker.transport:from_environment --factory --host 0.0.0.0 --port 8080`.
Do not publish a host port; deployment/network restrictions are a later PR.
/health is process liveness only, not proof that credentials or Inventory work.

Tests use genuine synthetic RSA signatures and ASGI HTTP requests, with an
HTTPX mock transport for Inventory. They cover identity failures, size limits,
credential rereading, non-200/timeout handling and acknowledgement mismatch.
They do not prove live DNS/network isolation, TLS, Inventory persistence,
lost acknowledgements across restart, or durable relay retries. HTTP is allowed
only on the isolated local development network; external transport needs TLS.
