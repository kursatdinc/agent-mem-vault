---
id: ae3ba645-f01c-50dd-8fca-25d4ec65e8a6
kind: handoff
namespace: project/harbor-api
agent: handoff
title: Handoff to codex
created: 2026-03-09T09:01:00Z
updated: 2026-03-10T09:03:00Z
revision: 2
visibility: internal
validity: valid
tags: [handoff]
superseded_by: '[[project-harbor-api/handoff/2026-03-10-handoff-to-codex-3ea7ecc4]]'
to: codex
read: true
read_at: 2026-03-10T09:02:00Z
agent-written: true
---
## Summary
Batch the orders backfill

## Full Context
The backfill in migrations/0007 needs batching. Start with a batch size of 1000 and measure the lock time.

<!-- avm:related:start -->
## Related
- Superseded by [[project-harbor-api/handoff/2026-03-10-handoff-to-codex-3ea7ecc4|Handoff to codex]]
<!-- avm:related:end -->
