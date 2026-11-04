---
id: ae3ba645-f01c-50dd-8fca-25d4ec65e8a6
kind: snapshot
namespace: project/harbor-api
agent: claude-code
title: harbor-api state after the PostgreSQL move
created: 2026-03-10T09:01:00Z
updated: 2026-03-10T09:01:00Z
revision: 1
visibility: internal
validity: valid
tags: [snapshot]
agent-written: true
---
Storage runs on PostgreSQL 16. The orders backfill is the one open risk. The in-process cache idea was rejected.
