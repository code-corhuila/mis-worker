# Owner-Confirmed Stock Event Consumer

Worker keeps no stock tables or signing keys. The consumer core validates Inventory's
v1 event and calls an Inventory-owned effect port. The intended API must commit the
event inbox and its effect/checkpoint atomically before returning eventId, sequence
and applied. A duplicate/stale response with applied=false can still be acknowledged.

The core checks the exact event ID/sequence in that response and propagates owner
failures instead of returning accepted. Event ID must match movement ID, signed
delta must equal quantity according to movement type, and IDs/numeric fields are
canonical. Validated flat payloads are immutable. The schema is a pinned copy of
mis-inventory-api/docs/stock-changed.schema.json; change producer/consumer together.

This PR provides only the port, validation and unit-tested acknowledgement rule.
The owner is mocked in these tests. No persistence, actual deduplication, HTTP/JWT
transport, machine identity issuance, relay lease/retry or alert job exists yet.
Do not deploy this core as an unauthenticated receiver or close HU-EVT-001 on it.
