import asyncio
import os
import sys
from pathlib import Path

from django.conf import settings
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The MCP filesystem server will operate on the same root directory as Django's file storage
# It is media/ from the settings
MCP_ROOT = Path(settings.MCP_FILESYSTEM_ROOT).resolve()

# Start the custom Python MCP server.
# This server is located in the project root under mcp_server/.
custom_server_params = StdioServerParameters(
    command=sys.executable,
    args=[
        "-m",
        "mcp_server.server",
    ],
    env={
        **os.environ,
        "PYTHONPATH": str(settings.BASE_DIR),
        "MCP_FILESYSTEM_ROOT": str(MCP_ROOT),
        "DJANGO_SETTINGS_MODULE": os.environ.get(
            "DJANGO_SETTINGS_MODULE",
            "config.settings",
        ),
    },
)


# The tools below are wrappers around the tools exposed by the custom MCP filesystem server
# _call_custom_tool is a helper function that connects to the MCP server and calls a tool with the given arguments, returning the raw result from the MCP server
async def _call_custom_tool(tool_name: str, arguments: dict):
    """Call one tool on the custom Python MCP server."""

    async with stdio_client(custom_server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

# _list_custom_tools is a helper function that lists the tools exposed by the custom MCP server 
async def _list_custom_tools():
    """List tools exposed by the custom Python MCP server."""

    async with stdio_client(custom_server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.list_tools()

# _extract_text is a helper function that extracts plain text from an MCP result, handling different possible formats of the result
def _extract_text(result) -> str:
    """Extract plain text from an MCP result."""

    if hasattr(result, "structuredContent") and result.structuredContent:
        content = result.structuredContent.get("content")

        if content is not None:
            return str(content)

    if hasattr(result, "content") and result.content:
        parts = []

        for item in result.content:
            text = getattr(item, "text", None)

            if text is not None:
                parts.append(text)

        if parts:
            return "\n".join(parts)

    return ""


def call_custom_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Call one tool on the custom Python MCP server."""

    result = asyncio.run(_call_custom_tool(tool_name, arguments))

    # If the result is an error raise an exception with the error message
    if result.isError:
        raise RuntimeError(_extract_text(result))
    
    return _extract_text(result)


def list_custom_mcp_tools() -> list[str]:
    """Return names of tools exposed by the custom Python MCP server."""

    result = asyncio.run(_list_custom_tools())
    return [tool.name for tool in result.tools]
