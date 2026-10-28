import argparse
import sys
from importlib.metadata import version

from agent_vault_memory.config import Config, ConfigError, load_config
from agent_vault_memory.doctor import run_doctor
from agent_vault_memory.format import format_records
from agent_vault_memory.runtime import open_store
from agent_vault_memory.server import create_server
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

    search = commands.add_parser("search", help="search records by text")
    search.add_argument("query")
    _add_filters(search)
    search.add_argument("--type", choices=["context", "handoff"])
    search.add_argument("--kind")
    search.add_argument("--tag", action="append", dest="tags")

    handoffs = commands.add_parser("handoffs", help="list handoffs")
    _add_filters(handoffs)
    handoffs.add_argument("--status", choices=["all", "pending", "read"], default="all")
    return parser


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--namespace")
    parser.add_argument("--agent")
    parser.add_argument("--limit", type=float)


def _run_server(config: Config) -> int:
    store = open_store(config)
    store.vault.clean_tmp_leftovers()
    create_server(store).run()
    return 0


def _print_records(records: list, empty: str) -> int:
    print(format_records(records) if records else empty)
    return 0


def _dispatch(args: argparse.Namespace, config: Config) -> int:
    if args.command is None:
        return _run_server(config)
    if args.command == "doctor":
        return run_doctor(config)
    store = open_store(config)
    if args.command == "list":
        records = store.list_contexts(args.namespace, args.agent, args.tags, args.type, args.kind, args.limit)
        return _print_records(records, "No saved context yet.")
    if args.command == "search":
        records = store.search_memory(
            args.namespace, args.query, args.agent, args.tags, args.type, args.kind, limit=args.limit
        )
        return _print_records(records, "No matching memory found.")
    return _print_records(
        store.list_handoffs(args.namespace, args.agent, args.status, args.limit), "No handoffs found."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args, load_config())
    except (ConfigError, VaultError, ValueError, TypeError) as error:
        print(f"agent-vault-memory: {error}", file=sys.stderr)
        return 2


def run() -> None:
    sys.exit(main())
