import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from agent_vault_memory.config import Config, ConfigError, load_config
from agent_vault_memory.doctor import run_doctor
from agent_vault_memory.format import format_records
from agent_vault_memory.hooks import CLIENTS, run_hook
from agent_vault_memory.legacy import parse_store
from agent_vault_memory.runtime import open_store
from agent_vault_memory.store import Store
from agent_vault_memory.vault import VaultError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-vault-memory",
        description=(
            "MCP server giving coding agents durable shared memory stored in an Obsidian vault. "
            "Without a subcommand it runs the MCP server over stdio."
        ),
    )
    parser.add_argument("--version", action="version", version=version("agent-vault-memory"))
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("doctor", help="check configuration, vault and record counts")

    listing = commands.add_parser("list", help="list recent records")
    _add_filters(listing)
    listing.add_argument("--type", choices=["context", "handoff"])
    listing.add_argument("--kind")
    listing.add_argument("--tag", action="append", dest="tags")
    listing.add_argument("--include-private", action="store_true")

    search = commands.add_parser("search", help="search records by text")
    search.add_argument("query")
    _add_filters(search)
    search.add_argument("--type", choices=["context", "handoff"])
    search.add_argument("--kind")
    search.add_argument("--tag", action="append", dest="tags")
    search.add_argument("--include-private", action="store_true")

    importing = commands.add_parser("import", help="one-time, idempotent import of a shared-memory-mcp contexts.json")
    importing.add_argument("source", type=Path)
    importing.add_argument(
        "--namespace-map",
        action="append",
        default=[],
        type=_namespace_mapping,
        metavar="OLD=NEW",
        help="import records of namespace OLD into namespace NEW; repeatable",
    )

    handoffs = commands.add_parser("handoffs", help="list handoffs")
    _add_filters(handoffs)
    handoffs.add_argument("--status", choices=["all", "pending", "read"], default="all")

    hook = commands.add_parser("hook", help="client hook entry points; they need features.hooks")
    events = hook.add_subparsers(dest="action", required=True)
    for action, text in (
        ("session-start", "print the project brief for a SessionStart hook"),
        ("stop", "print a nudge to record decisions for a Stop hook"),
        ("print-config", "print the client settings snippet that installs both hooks"),
    ):
        events.add_parser(action, help=text).add_argument("--client", choices=CLIENTS, required=True)
    return parser


def _namespace_mapping(text: str) -> tuple[str, str]:
    old, separator, new = text.partition("=")
    if not (old and separator and new):
        raise argparse.ArgumentTypeError(f"expected OLD=NEW, got {text!r}")
    return old, new


def _run_import(args: argparse.Namespace, store: Store) -> int:
    prepared, errors = parse_store(args.source, dict(args.namespace_map))
    report = store.import_records(prepared)
    errors += report.errors
    print(f"imported: {report.imported}")
    print(f"skipped: {report.skipped}")
    print(f"superseded-marked: {report.superseded_marked}")
    print(f"errors: {len(errors)}")
    for error in errors:
        print(f"  {error}")
    return 0


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--namespace")
    parser.add_argument("--agent")
    parser.add_argument("--limit", type=float)


def _run_server(config: Config) -> int:
    from agent_vault_memory.server import create_server

    store = open_store(config)
    store.vault.clean_tmp_leftovers()
    create_server(store).run()
    return 0


def _print_records(records: list, empty: str, mark_rejected: bool = False) -> int:
    print(format_records(records, mark_rejected) if records else empty)
    return 0


def _dispatch(args: argparse.Namespace, config: Config) -> int:
    if args.command is None:
        return _run_server(config)
    if args.command == "doctor":
        return run_doctor(config)
    store = open_store(config)
    if args.command == "import":
        return _run_import(args, store)
    if args.command == "list":
        records = store.list_contexts(
            args.namespace, args.agent, args.tags, args.type, args.kind, args.limit, args.include_private
        )
        return _print_records(records, "No saved context yet.", store.visibility_filter)
    if args.command == "search":
        records = store.search_memory(
            args.namespace,
            args.query,
            args.agent,
            args.tags,
            args.type,
            args.kind,
            limit=args.limit,
            include_private=args.include_private,
        )
        return _print_records(records, "No matching memory found.", store.visibility_filter)
    return _print_records(
        store.list_handoffs(args.namespace, args.agent, args.status, args.limit), "No handoffs found."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "hook":
        return run_hook(args.action, args.client)
    try:
        return _dispatch(args, load_config())
    except (ConfigError, VaultError, ValueError, TypeError) as error:
        print(f"agent-vault-memory: {error}", file=sys.stderr)
        return 2


def run() -> None:
    sys.exit(main())
