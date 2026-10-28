---
id: 728f9c30-c5c1-514b-b48c-87b0b3f4da58
kind: risk
namespace: project/harbor-api
agent: codex
title: Migration script locks the orders table
created: 2026-03-08T09:03:00Z
updated: 2026-03-08T09:03:00Z
revision: 1
visibility: internal
validity: valid
tags: [storage, migration]
status: open
related_files: [migrations/0007_backfill_orders.sql]
next_action: Split the backfill into batches of 5000 rows
agent-written: true
---
The backfill runs inside one transaction and holds a lock on `orders` for about 40 seconds on a copy of production data. Writes queue up behind it.
