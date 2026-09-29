from mcp_client.tools import get_tools


def get_tools_for_context(context):
    """Return tools for a chat context."""

    # For now, we return all tools, but in the future we could filter them based on the context 
    return get_tools()