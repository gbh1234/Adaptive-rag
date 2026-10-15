from app.tools.factory import build_tool_registry


def test_registry_has_fifteen_tools() -> None:
    class _Retriever:
        pass

    registry = build_tool_registry(_Retriever())  # type: ignore[arg-type]
    assert len(registry.names()) == 15
    assert "get_order" in registry.names()
    assert "escalate_to_human" in registry.names()
