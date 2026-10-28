import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def run_session(tmp_path, scenario, config_text=""):
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(config_text, encoding="utf-8")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from agent_vault_memory.cli import run; run()"],
        env={"AGENT_VAULT_MEMORY_VAULT": str(vault_root), "AGENT_VAULT_MEMORY_CONFIG": str(config_file)},
    )

    async def session_run():
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await scenario(session)

    return asyncio.run(asyncio.wait_for(session_run(), timeout=60))


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    return result.content[0].text
