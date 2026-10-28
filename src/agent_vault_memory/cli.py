import argparse
from importlib.metadata import version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-vault-memory",
        description="MCP server giving coding agents durable shared memory stored in an Obsidian vault.",
    )
    parser.add_argument("--version", action="version", version=version("agent-vault-memory"))
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
