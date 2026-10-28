# Contributing

Thanks for taking the time. Bug reports, ideas and pull requests are all welcome.

- Questions and ideas: [Discussions](https://github.com/kursatdinc/agent-mem-vault/discussions).
- Bugs and feature requests: [Issues](https://github.com/kursatdinc/agent-mem-vault/issues), using the templates.
- Security problems: see [SECURITY.md](SECURITY.md), not a public issue.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer. macOS and Linux are supported;
the file lock uses `fcntl`, so Windows is not.

```sh
git clone https://github.com/kursatdinc/agent-mem-vault
cd agent-mem-vault
uv sync
```

## Check your change

```sh
uv run ruff check          # lint, including import order
uv run pytest -q           # the full suite, a few seconds
```

CI runs the same two commands on Linux and macOS with Python 3.12 and 3.13.

Tests use temporary vaults and synthetic data only. Never put real notes, paths or secrets in a
test or a fixture. A behavior change comes with a test that fails without it.

Run the server against a scratch vault while you work:

```sh
export AGENT_MEM_VAULT_VAULT="$(mktemp -d)"
uv run agent-mem-vault doctor
```

The demo vault in `examples/demo-vault` is generated, not hand-written. If you change the record
format or the generated notes, regenerate it and commit the result:

```sh
uv run python scripts/build_demo_vault.py
```

## Pull requests

- Keep a pull request to one logical change.
- [docs/DESIGN.md](docs/DESIGN.md) is the contract. If a change alters behavior it describes,
  update it in the same pull request.
- Add a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- Runtime dependencies stay at `mcp`, `PyYAML` and `PyStemmer`. Please open a discussion before
  adding one.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org): `type: short summary` in the imperative
mood, for example `fix: keep hand edits when a handoff is acknowledged`. Common types are `feat`,
`fix`, `docs`, `refactor`, `test` and `chore`. Add a body when the why is not obvious from the diff.

## Releasing

Maintainers: see [docs/RELEASING.md](docs/RELEASING.md).
