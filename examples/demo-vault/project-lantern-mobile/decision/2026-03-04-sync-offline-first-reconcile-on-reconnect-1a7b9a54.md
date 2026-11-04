---
id: 1a7b9a54-b2d9-598f-959b-9be103a277b4
kind: decision
namespace: project/lantern-mobile
agent: claude-code
title: Sync offline first, reconcile on reconnect
created: 2026-03-04T09:01:00Z
updated: 2026-03-04T09:01:00Z
revision: 1
visibility: internal
validity: valid
tags: [sync]
status: accepted
agent-written: true
---
Field staff work in tunnels with no signal. The app writes locally and reconciles when the network returns, with last-writer-wins per field.
