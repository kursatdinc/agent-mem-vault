import argparse
import sys
from importlib.metadata import version

from agent_mem_vault.config import Config, ConfigError, load_config
from agent_mem_vault.doctor import run_doctor
from agent_mem_vault.format import format_records
from agent_mem_vault.hooks import CLIENTS, run_hook
from agent_mem_vault.migrate import Move, archive_legacy_handoffs, legacy_handoffs
from agent_mem_vault.runtime import open_store
from agent_mem_vault.vault import VaultError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-mem-vault",
        description=(
            "MCP server giving coding agents durable shared memory stored in an Obsidian vault. "
            "Without a subcommand it runs the MCP server over stdio."
        ),
    )
    parser.add_argument("--version", action="version", version=version("agent-mem-vault"))
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("doctor", help="check configuration, vault and record counts")

    listing = commands.add_parser("list", help="list recent records")
    _add_filters(listing)
    listing.add_argument("--kind")
    listing.add_argument("--tag", action="append", dest="tags")
    listing.add_argument("--include-private", action="store_true")
    listing.add_argument("--include-closed", action="store_true")

    search = commands.add_parser("search", help="search records by text")
    search.add_argument("query")
    _add_filters(search)
    search.add_argument("--kind")
    search.add_argument("--tag", action="append", dest="tags")
    search.add_argument("--include-private", action="store_true")
    search.add_argument("--include-closed", action="store_true")

    migrate = commands.add_parser("migrate", help="archive the handoff records left by agent-mem-vault 1.x")
    mode = migrate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print what would move and change nothing")
    mode.add_argument(
        "--apply", action="store_true", help="move them, rebuild every hub and commit when the vault is a git work tree"
    )

    rebuild = commands.add_parser(
        "rebuild-hubs", help="rebuild the generated hub notes of the given namespace folders, or of all of them"
    )
    rebuild.add_argument("slugs", nargs="*", metavar="SLUG", help="a namespace folder, for example project-harbor-api")

    hook = commands.add_parser("hook", help="client hook entry points; they need features.hooks")
    events = hook.add_subparsers(dest="action", required=True)
    for action, text in (
        ("session-start", "print the project brief for a SessionStart hook"),
        ("stop", "print a nudge to update the companion cards for a Stop hook"),
        ("print-config", "print the client settings snippet that installs both hooks"),
    ):
        events.add_parser(action, help=text).add_argument("--client", choices=CLIENTS, required=True)
    return parser


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--namespace")
    parser.add_argument("--agent")
    parser.add_argument("--limit", type=float)


def _run_server(config: Config) -> int:
    from agent_mem_vault.server import create_server

    store = open_store(config)
    store.vault.clean_tmp_leftovers()
    create_server(store).run()
    return 0


def _print_records(records: list, empty: str, mark_rejected: bool = False) -> int:
    print(format_records(records, mark_rejected) if records else empty)
    return 0


def _migrate(store, apply: bool) -> int:
    moves, hubs = archive_legacy_handoffs(store) if apply else (legacy_handoffs(store.vault.root), [])
    for move in moves:
        print(_move_line(move, apply))
    count = sum(not move.blocked for move in moves)
    noun = "handoff" if count == 1 else "handoffs"
    if not moves:
        print("No legacy handoffs found.")
    elif apply:
        print(f"Moved {count} legacy {noun}.")
    else:
        print(f"Dry run: {count} legacy {noun} to move. Run `agent-mem-vault migrate --apply` to move them.")
    if apply:
        _print_hub_changes(store.vault.root, hubs)
    return 0


def _rebuild_hubs(store, slugs: list[str]) -> int:
    touched, unknown = store.rebuild_hubs(slugs or None)
    for slug in unknown:
        print(f"agent-mem-vault: no namespace folder named {slug}: skipped", file=sys.stderr)
    _print_hub_changes(store.vault.root, touched)
    return 0


def _print_hub_changes(root, touched: list[str]) -> None:
    for path in touched:
        print(f"{'wrote' if (root / path).exists() else 'removed'} {path}")
    if not touched:
        print("Hubs are up to date.")


def _move_line(move: Move, apply: bool) -> str:
    if move.blocked:
        return f"skipped {move.source}: {move.target} already exists"
    return f"{'moved' if apply else 'would move'} {move.source} -> {move.target}"


def _dispatch(args: argparse.Namespace, config: Config) -> int:
    if args.command is None:
        return _run_server(config)
    if args.command == "doctor":
        return run_doctor(config)
    store = open_store(config)
    if args.command == "migrate":
        return _migrate(store, args.apply)
    if args.command == "rebuild-hubs":
        return _rebuild_hubs(store, args.slugs)
    if args.command == "list":
        records = store.list_contexts(
            args.namespace, args.agent, args.tags, args.kind, args.limit, args.include_private, args.include_closed
        )
        return _print_records(records, "No saved context yet.", store.visibility_filter)
    records = store.search_memory(
        args.namespace,
        args.query,
        args.agent,
        args.tags,
        args.kind,
        args.limit,
        args.include_private,
        args.include_closed,
    )
    return _print_records(records, "No matching memory found.", store.visibility_filter)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "hook":
        return run_hook(args.action, args.client)
    try:
        return _dispatch(args, load_config())
    except (ConfigError, VaultError, ValueError, TypeError) as error:
        print(f"agent-mem-vault: {error}", file=sys.stderr)
        return 2


def run() -> None:
    sys.exit(main())
