---
id: 234bc139-823f-5c1c-b7bb-d37ea1c3ee3c
kind: decision
namespace: project/harbor-api
agent: claude-code
title: Move order storage to PostgreSQL
created: 2026-03-06T09:01:00Z
updated: 2026-03-08T09:02:00Z
revision: 2
visibility: internal
validity: valid
tags: [storage]
status: accepted
supersedes: ['[[project-harbor-api/decision/2026-03-02-use-sqlite-for-the-first-release-d61740a1]]']
superseded_by: '[[project-harbor-api/decision/2026-03-08-pin-postgresql-16-in-ci-and-production-eb0b3836]]'
agent-written: true
---
The pilot grew to three workers, which SQLite cannot serve safely. PostgreSQL gives concurrent writers and point-in-time recovery.

<!-- avm:related:start -->
## Related
- Supersedes [[project-harbor-api/decision/2026-03-02-use-sqlite-for-the-first-release-d61740a1|Use SQLite for the first release]]
- Superseded by [[project-harbor-api/decision/2026-03-08-pin-postgresql-16-in-ci-and-production-eb0b3836|Pin PostgreSQL 16 in CI and production]]
<!-- avm:related:end -->
