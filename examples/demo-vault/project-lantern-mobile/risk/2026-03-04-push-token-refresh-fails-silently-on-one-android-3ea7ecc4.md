---
id: 3ea7ecc4-8a5b-5187-b434-2de184e59933
kind: risk
namespace: project/lantern-mobile
agent: codex
title: Push token refresh fails silently on one Android version
created: 2026-03-04T09:02:00Z
updated: 2026-03-04T09:02:00Z
revision: 1
visibility: internal
validity: valid
tags: [notifications, android]
status: open
agent-written: true
---
On Android 14 the refreshed token is not sent to the backend when the app is in the background. Notifications stop until the next cold start.
