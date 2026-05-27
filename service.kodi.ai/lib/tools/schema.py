"""Convert @tool registry → OpenAI tool-use function schema list."""
from __future__ import annotations
from . import registry


def get_tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": fn.tool_name,
                "description": fn.description,
                "parameters": fn.tool_schema,
            },
        }
        for fn in registry.values()
    ]
