import pytest

from agent_vault_memory.cli import main


def test_help_exits_zero_and_names_the_program(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "agent-vault-memory" in capsys.readouterr().out
