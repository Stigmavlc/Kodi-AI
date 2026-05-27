def test_tool_decorator_registers():
    from lib.tools import tool, registry, ToolResult
    @tool(name="dummy", description="d", schema={"type": "object", "properties": {}},
          tier="immediate")
    def dummy(): return ToolResult(success=True, requested="dummy()", output="ok",
                                    actual_state_after=None, error=None,
                                    snapshot_id=None, cost_seconds=0.0)
    assert "dummy" in registry
    res = registry["dummy"]()
    assert res.success


def test_tool_routing_immediate_non_disruptive():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t1", description="", schema={"type": "object"}, tier="immediate")
    def t1(): pass
    decision = tool_routing_decision(t1, args={})
    assert decision == "apply_immediately"


def test_tool_routing_confirm():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t2", description="", schema={"type": "object"}, tier="confirm")
    def t2(): pass
    assert tool_routing_decision(t2, args={}) == "needs_confirmation"


def test_tool_routing_immediate_disruptive_downgrades():
    from lib.tools import tool, ToolResult, tool_routing_decision
    @tool(name="t3", description="", schema={"type": "object"}, tier="immediate",
          disruptive=lambda args: args.get("force"))
    def t3(force=False): pass
    assert tool_routing_decision(t3, args={"force": True}) == "needs_confirmation"
    assert tool_routing_decision(t3, args={"force": False}) == "apply_immediately"
