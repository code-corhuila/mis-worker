# ADR-EVT-003: private Worker deployment

Status: accepted; shared root integration and durable relay remain pending.

deploy/compose.yml is a fragment of the platform composition, not a standalone
root. It joins platform and requires healthy Inventory. There is no host port,
database, broker or volume storing stock. Runtime uses UID/GID 10001, read-only
root, dropped capabilities, no-new-privileges and a temporary /tmp filesystem.

All identity/key/path variables are required. The ignored env/ENV.env must use
the subjects and key ID registered in Security, never new UUIDs on renewal.
The three .example files intentionally have blank identity fields: they are
not runnable credentials. The public key and JWT are mounted as a read-only
directory with create_host_path=false, so Security's atomic file replacement
is visible without recreating Worker. Relative paths resolve from deploy/.
Production credentials require host ACLs/owner-only permissions readable by
UID 10001; do not copy the synthetic test fixture permissions to live secrets.

The image build runs all core/transport tests, then copies only dependencies,
Worker code and the event contract into runtime. Docker context excludes env,
secrets and Git. /health proves process liveness only, not Inventory or token
readiness. The root composition must load this fragment and the ignored env
explicitly; this PR neither changes nor restarts the existing platform.

Run `python tests/check_deployment.py` with requirements installed and Docker.
It creates a uniquely named isolated internal network, synthetic RSA tokens,
a real Worker container and an HTTP owner stub. It verifies signed requests,
invalid identities, owner-confirmed duplicate acknowledgements, trace forwarding,
atomic credential renewal visible through the directory mount, and container
restrictions. Missing required configuration is rejected before deployment.
Cleanup removes only this unique test project, not dev/qa/main or their data.

The stub has in-memory receipts, not Inventory's database. This test does not
prove durable owner effects, outbox leases, lost acknowledgements across restart,
alert processing, shared platform isolation or release QA. CI repeats this test;
its remote result is pending until publication. HU-EVT-001 remains open.
