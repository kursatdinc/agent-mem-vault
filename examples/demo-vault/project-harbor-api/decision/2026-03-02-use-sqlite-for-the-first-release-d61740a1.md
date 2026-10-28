---
id: d61740a1-14d0-577a-813c-df613269f369
kind: decision
namespace: project/harbor-api
agent: claude-code
title: Use SQLite for the first release
created: 2026-03-02T09:01:00Z
updated: 2026-03-06T09:02:00Z
revision: 2
visibility: internal
validity: valid
tags: [storage]
status: superseded
superseded_by: '[[project-harbor-api/decision/2026-03-06-move-order-storage-to-postgresql-234bc139]]'
agent-written: true
---
Orders fit on one node for the pilot. SQLite keeps deployment to a single file and needs no extra service.

<!-- avm:related:start -->
## Related
- Superseded by [[project-harbor-api/decision/2026-03-06-move-order-storage-to-postgresql-234bc139|Move order storage to PostgreSQL]]
<!-- avm:related:end -->
