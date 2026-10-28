---
id: c463660e-f81c-5099-abab-920272898e21
kind: decision
namespace: project/harbor-api
agent: claude-code
title: Cache order lookups in process memory
created: 2026-03-02T09:02:00Z
updated: 2026-03-03T09:01:00Z
revision: 2
visibility: internal
validity: rejected
tags: [performance]
rejected_reason: Workers do not share memory, so cached orders go stale between processes.
agent-written: true
---
A per-process dict would cut the lookup latency without any new infrastructure.
