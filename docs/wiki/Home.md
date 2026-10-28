# agent-mem-vault

Memory your coding agents share, and you can read, link and fix in Obsidian.

agent-mem-vault is an [MCP](https://modelcontextprotocol.io) server. Claude Code, Codex and any
other MCP client use it to record decisions, risks, handoffs and project snapshots as Markdown notes
in an [Obsidian](https://obsidian.md) vault, and to read them back in later sessions. You see the same
notes in Obsidian, with its graph, backlinks and Bases, and you can correct them there.

## Start here

| If you want to | Read |
|---|---|
| Install it and see it work | [Getting Started](https://github.com/kursatdinc/agent-mem-vault/wiki/Getting-Started) |
| Change settings and turn on optional features | [Configuration](https://github.com/kursatdinc/agent-mem-vault/wiki/Configuration) |
| Know exactly what each tool takes and returns | [Tools Reference](https://github.com/kursatdinc/agent-mem-vault/wiki/Tools-Reference) |
| Understand or hand-edit a note | [Record Format](https://github.com/kursatdinc/agent-mem-vault/wiki/Record-Format) |
| Use the graph and the dashboard | [Obsidian Integration](https://github.com/kursatdinc/agent-mem-vault/wiki/Obsidian-Integration) |
| Pass work between agents | [Multi-Agent Handoffs](https://github.com/kursatdinc/agent-mem-vault/wiki/Multi-Agent-Handoffs) |
| Find a quick answer | [FAQ](https://github.com/kursatdinc/agent-mem-vault/wiki/FAQ) |

## The idea in four lines

- One Markdown file per record, grouped by project namespace, with YAML frontmatter.
- The server keeps no database and no index. Every query reads the files.
- Writes are locked and atomic, and a note you edited by hand is never overwritten silently.
- Everything runs locally: no network calls, and Obsidian does not need to be open.

## Links

- [Repository](https://github.com/kursatdinc/agent-mem-vault) and its
  [README](https://github.com/kursatdinc/agent-mem-vault#readme)
- [Design contract](https://github.com/kursatdinc/agent-mem-vault/blob/main/docs/DESIGN.md)
- [Changelog](https://github.com/kursatdinc/agent-mem-vault/blob/main/CHANGELOG.md) and
  [release process](https://github.com/kursatdinc/agent-mem-vault/blob/main/docs/RELEASING.md)
- [Discussions](https://github.com/kursatdinc/agent-mem-vault/discussions) and
  [Issues](https://github.com/kursatdinc/agent-mem-vault/issues)
