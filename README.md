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
The unit suite uses a fake owner: no durable inbox, transport, retries or alerts are
implemented yet. See docs/ADR-EVT-001-owner-confirmed-consumer.md for the boundary.
