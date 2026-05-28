import pytest


@pytest.fixture
def isolated_registry():
    """MED-2: snapshot + restore the SHARED module-global tool registry.

    test_get_tool_schemas_emits_openai_format used to call registry.clear() and
    never restore it, permanently wiping the registry for the rest of the
    session. The suite only passed because alphabetical collection happened to
    run registry-dependent tests (e.g. test_chat_toolset_excludes_http_and_file_write)
    first. Under any reordering (pytest-randomly / -p no:randomly with a different
    file order / xdist), those tests then saw an empty registry and failed.

    This fixture saves a shallow copy before the test mutates the global and
    restores the exact contents in teardown, so the test can clear/populate
    freely without leaking state.
    """
    from lib.tools import registry
    saved = dict(registry)
    try:
        yield registry
    finally:
        registry.clear()
        registry.update(saved)


def test_get_tool_schemas_emits_openai_format(isolated_registry):
    from lib.tools import tool, ToolResult
    from lib.tools.schema import get_tool_schemas
    registry = isolated_registry
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
