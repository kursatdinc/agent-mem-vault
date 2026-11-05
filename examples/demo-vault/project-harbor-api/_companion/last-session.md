---
kind: companion
namespace: project/harbor-api
updated: 2026-03-10T09:02:00Z
agent-written: true
---
Pinned PostgreSQL 16 in CI and wrote the state snapshot. Unverified: the batched backfill has not run on a production copy yet. Next: run it with batches of 5000 rows and log the lock time.
