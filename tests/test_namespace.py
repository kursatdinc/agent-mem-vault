import subprocess

import pytest

from agent_mem_vault.cli import main
from agent_mem_vault.store import Store
from mcp_session import call, run_session


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "harbor-api"
    (root / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    return root


def test_a_tool_call_without_namespace_lands_in_the_git_root_namespace_of_the_server(tmp_path, repo):
    async def scenario(session):
        await call(session, "save_context", agent="a", title="Repo note", content="c")
        return (
            await call(session, "list_contexts", namespace="project/harbor-api"),
            await call(session, "get_project_brief"),
        )

    listed, brief = run_session(tmp_path / "server", scenario, "default_namespace: fallback\n", cwd=repo / "src")

    assert listed.startswith("1. [note] (project/harbor-api) Repo note - a - ")
    assert brief.startswith("**Project brief for project/harbor-api**\n\n## Active records\n- [note] Repo note - id ")


def test_outside_a_git_repository_the_configured_default_namespace_applies(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    async def scenario(session):
        await call(session, "save_context", agent="a", title="Loose note", content="c")
        return await call(session, "list_contexts", namespace="fallback")

    listed = run_session(tmp_path / "server", scenario, "default_namespace: fallback\n", cwd=plain)

    assert listed.startswith("1. [note] (fallback) Loose note - a - ")


def test_cli_listing_without_namespace_follows_the_current_repository(configured_vault, repo, monkeypatch, capsys):
    Store(configured_vault).save_context(agent="a", title="Harbor note", content="c", namespace="project/harbor-api")
    Store(configured_vault).save_context(agent="a", title="Default note", content="c")
    monkeypatch.chdir(repo / "src")

    assert main(["list"]) == 0

    assert capsys.readouterr().out.startswith("1. [note] (project/harbor-api) Harbor note - a - ")
