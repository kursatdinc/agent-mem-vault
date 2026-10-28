# Security policy

## Supported versions

Security fixes go into the latest release. Please update before reporting, if you can.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability.

Use GitHub's private vulnerability reporting: open the
[Security tab](https://github.com/kursatdinc/agent-mem-vault/security) and choose
**Report a vulnerability**, or go straight to
[the advisory form](https://github.com/kursatdinc/agent-mem-vault/security/advisories/new).
The report reaches only the maintainer.

Include what you can: the version, how to reproduce, what an attacker gains, and any suggested fix.
The maintainer aims to acknowledge a report within a few days. A confirmed vulnerability is fixed in a new
release and published as a GitHub Security Advisory, crediting you if you wish.

## What is in scope

The server is local: it reads and writes Markdown files in the vault you configure and makes no
network calls. These are the things worth reporting:

- reading or writing outside the configured vault, for example through a symlink or a crafted path;
- secrets in tool input that survive redaction into a note;
- a crafted note or tool input that crashes the server or corrupts other records.

Anything that needs write access to your vault or your client configuration to begin with is
outside the threat model: whoever can edit the vault can already edit the memory.
