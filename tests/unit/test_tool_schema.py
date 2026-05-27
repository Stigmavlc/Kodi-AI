def test_get_tool_schemas_emits_openai_format():
    from lib.tools import tool, registry, ToolResult
    from lib.tools.schema import get_tool_schemas
    registry.clear()
    @tool(name="foo", description="does foo",
          schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
          tier="immediate")
    def foo(x: str): return ToolResult(success=True, requested="foo", output=None,
                                        actual_state_after=None, error=None,
                                        snapshot_id=None, cost_seconds=0.0)
    schemas = get_tool_schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "foo"
    assert s["function"]["description"] == "does foo"
    assert s["function"]["parameters"]["properties"]["x"]["type"] == "string"
