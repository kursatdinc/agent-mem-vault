---
id: 9f04bcfc-d76f-5dfd-8325-4639aa4fb90a
kind: snapshot
namespace: project/harbor-api
agent: claude-code
title: harbor-api state after the PostgreSQL move
created: 2026-03-10T09:04:00Z
updated: 2026-03-10T09:04:00Z
revision: 1
visibility: internal
validity: valid
tags: [snapshot]
agent-written: true
---
Storage runs on PostgreSQL 16. The orders backfill is the one open risk and is handed to Codex. The in-process cache idea was rejected.
