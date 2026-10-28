---
id: eb0b3836-d3f8-50df-9456-8fc9cd4e3915
kind: decision
namespace: project/harbor-api
agent: codex
title: Pin PostgreSQL 16 in CI and production
created: 2026-03-08T09:01:00Z
updated: 2026-03-08T09:01:00Z
revision: 1
visibility: internal
validity: valid
tags: [storage, ci]
status: accepted
supersedes: ['[[project-harbor-api/decision/2026-03-06-move-order-storage-to-postgresql-234bc139]]']
agent-written: true
---
CI uses the same major version as production so migration scripts behave identically.

<!-- avm:related:start -->
## Related
- Supersedes [[project-harbor-api/decision/2026-03-06-move-order-storage-to-postgresql-234bc139|Move order storage to PostgreSQL]]
<!-- avm:related:end -->
