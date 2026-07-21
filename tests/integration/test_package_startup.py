import os
import subprocess
import sys


STARTUP_PROBE = r"""
import asyncio
from odoo_pulse import server  # noqa: F401 -- registration side effects
from odoo_pulse.runtime import mcp

async def main():
    tools = await mcp.list_tools()
    assert len(tools) == 31
    assert any(tool.name == "business_pulse" for tool in tools)

asyncio.run(main())
"""


def test_installed_package_starts_outside_repository(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-c", STARTUP_PROBE],
        check=True,
        cwd=tmp_path,
        env=env,
    )
