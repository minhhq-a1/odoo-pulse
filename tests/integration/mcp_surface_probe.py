from __future__ import annotations

import argparse
import asyncio
import json
import os
from importlib.metadata import version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", default="core,reports")
    parser.add_argument("--expected-tools", type=int, required=True)
    parser.add_argument("--expected-resources", type=int, default=1)
    parser.add_argument("--expected-sdk")
    parser.add_argument("--require-instructions", action="store_true")
    return parser.parse_args()


async def inspect_surface() -> dict:
    from odoo_pulse import server  # noqa: F401
    from odoo_pulse.mcp.app import mcp

    tools = sorted(tool.name for tool in await mcp.list_tools())
    resources = sorted(
        str(template.uriTemplate)
        for template in await mcp.list_resource_templates()
    )
    return {
        "sdk": version("mcp"),
        "tools": tools,
        "resources": resources,
        "instructions": mcp.instructions,
    }


def main() -> None:
    args = parse_args()
    os.environ["ODOO_TOOL_GROUPS"] = args.groups
    result = asyncio.run(inspect_surface())
    assert len(result["tools"]) == args.expected_tools, result
    assert len(result["resources"]) == args.expected_resources, result
    assert result["resources"] == ["odoo://{model}/{id}"], result
    if args.expected_sdk:
        assert result["sdk"] == args.expected_sdk, result
    if args.require_instructions:
        instructions = result["instructions"]
        assert instructions
        assert "Live business data" in instructions
        assert "NOT for Odoo source-code" in instructions
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
