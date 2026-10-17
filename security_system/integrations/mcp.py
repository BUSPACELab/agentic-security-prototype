"""MCP integration for resolving authenticated request identities."""

from mcp.server.lowlevel.server import request_ctx

from security_system.context import SecurityContext
from security_system.errors import MissingSecurityContext
from security_system.identity import IDENTITY_META_KEY, verify_identity


def current_mcp_security_context() -> SecurityContext | None:
    """Get the verified identity associated with the current MCP request.

    Returns:
        SecurityContext or None: The verified identity or None outside MCP.

    Raises:
        MissingSecurityContext: If an MCP request has no identity.
        PermissionError: If the received identity is invalid.
    """

    # The MCP SDK maintains a separate context for each active request
    # This is works for MCP SDK version 1.27.2 and prior probably (need testing)
    request_context = request_ctx.get(None)

    if request_context is None:
        return None

    # Read the custom metadata carried by this particular request
    metadata = request_context.meta
    values = metadata.model_extra if metadata is not None else None

    token = values.get(IDENTITY_META_KEY) if isinstance(values, dict) else None

    # Reject missing or unexpectedly large identity tokens
    if not isinstance(token, str) or len(token) > 4096:
        raise MissingSecurityContext("MCP request has no valid identity token.")

    return verify_identity(token)
