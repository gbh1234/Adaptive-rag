"""MCP integration layer."""

from app.mcp.adapter import merge_mcp_tools
from app.mcp.runtime import LOCAL_CATALOG

__all__ = ["merge_mcp_tools", "LOCAL_CATALOG"]
