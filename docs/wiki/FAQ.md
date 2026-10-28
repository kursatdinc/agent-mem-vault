# FAQ

## Does Obsidian have to be running?

No. The server reads and writes Markdown files directly. It never launches Obsidian. You need
Obsidian only to browse the graph and the dashboard, and `doctor` runs its extra Obsidian CLI check
only when Obsidian happens to be running.

## Does it need an API key, an embedding model or the network?

No. There is no database, no index and no network call. Search is stemmed keyword matching over
titles, content and tags. It will not find a record by meaning when no word matches.

## Where is my data?

In the folder you configured as the vault, one Markdown file per record under
`<namespace-slug>/<kind>/`. The only other things the server writes are the generated hub notes,
`_dashboards/memory.base` and a private `.agent-mem-vault/` folder with a lock file and temporary
files. See [Record Format](https://github.com/kursatdinc/agent-mem-vault/wiki/Record-Format).

## Can I put the vault in git, or sync it?

Yes. A vault in git gives you a full history of agent decisions, and `features.git_autocommit` can
commit each change for you. It never pushes. Sync tools that copy plain files work too; if two
machines write at the same moment through a sync service you may get conflicting copies, so prefer
git for that.

## Can I use my existing Obsidian vault?

Yes. The server only treats files at `<namespace-slug>/<kind>/*.md` with a known kind as records,
and ignores everything else. Your own notes are never touched. If you would rather keep things
apart, use a dedicated vault for agent memory.

## I edited a note in Obsidian. Will an agent overwrite it?

No. Updates check the record's `revision` and re-read the file under a lock. If you changed it in
between, the agent gets a conflict and reads the record again. See
[Obsidian Integration](https://github.com/kursatdinc/agent-mem-vault/wiki/Obsidian-Integration).

## A note shows up in `list_issues`. What now?

It looks like a record but cannot be used: broken YAML, a missing `id`, `kind` or `namespace`, an
unknown kind, a kind that does not match its folder, or a duplicate id. The reason is printed next to
the path. Fix the note in Obsidian and run `doctor` again. The server never modifies such files.

## What is a namespace? What should I use?

A namespace groups records, usually one per repository: `project/<repo name>`. Agents pass it on
each call. Records of other namespaces are never mixed in. If a call omits it, the
`default_namespace` setting applies.

## Two agents write at the same time. Is that safe?

Yes. Writes take an exclusive file lock on the vault and each file is replaced atomically.

## How do I keep something private?

Set `visibility: private` with `update_memory` or in the note. It then stays out of the project
brief and out of listings unless `include_private` is passed. This is about what agents load
automatically, not encryption: the file is still plain text in your vault. Secret-looking strings
(tokens, keys, `password=...`) are redacted before anything is written, but do not rely on that for
real credentials.

## A decision turned out wrong. Delete it?

Prefer marking it rejected with a reason (`validity: rejected`, `rejected_reason`). It leaves the
brief and stops steering agents, and the record of why it was wrong stays. To replace a decision,
save a new one that `supersedes` it.

## The hook does not run.

Check that `features.hooks` is on, that `agent-mem-vault` is on the `PATH` of the client
(`uv tool install agent-mem-vault`), and that the snippet from `agent-mem-vault hook print-config`
is in your client settings. Hooks exit 0 on every error and log the reason to stderr, so a broken
hook never blocks a session.

## Does it work on Windows?

Not yet. The file lock uses `fcntl`, so macOS and Linux are supported.

## Where do I ask something or report a bug?

Questions and ideas: [Discussions](https://github.com/kursatdinc/agent-mem-vault/discussions).
Bugs: [Issues](https://github.com/kursatdinc/agent-mem-vault/issues), with the output of
`agent-mem-vault doctor`. Vulnerabilities: see
[SECURITY.md](https://github.com/kursatdinc/agent-mem-vault/blob/main/SECURITY.md).
