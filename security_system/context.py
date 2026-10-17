"""Security context used by protected operations."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .errors import MissingSecurityContext


@dataclass(frozen=True)
class Principal:
    """Represent an authenticated actor's identity in the system."""

    # Identify the actor and the optional issuer of the identity
    subject: str
    issuer: str | None = None

    def __post_init__(self):
        """Validate and normalize the principal identifier."""

        # Reject missing or empty actor identifiers
        if self.subject is None:
            raise ValueError("Principal subject is required.")

        subject = str(self.subject).strip()

        if not subject:
            raise ValueError("Principal subject is required.")

        # Normalize the value while initializing the frozen dataclass
        object.__setattr__(self, "subject", subject)


@dataclass(frozen=True)
class SecurityContext:
    """Hold the security information associated with the current execution."""

    principal: Principal


# Store the current application's identity separately for concurrent executions
_current_context: ContextVar[SecurityContext | None] = ContextVar("security_system_context", default=None)


def current_security_context() -> SecurityContext:
    """Return the authenticated context of the current execution.

    Returns:
        SecurityContext: The authenticated security context.

    Raises:
        MissingSecurityContext: If no authenticated context is available.
        PermissionError: If the MCP identity is invalid.
    """

    from .integrations.mcp import current_mcp_security_context

    # Check whether this execution belongs to an MCP request
    context = current_mcp_security_context()

    if context is not None:
        return context

    # Otherwise use the identity captured by the application
    # This is useful when we call mcp_request_metadata() to attach the identity to an MCP request
    # and since we already have the identity in the current execution context we can use it
    context = _current_context.get()

    if context is None:
        raise MissingSecurityContext("A security context is required.")

    return context


@contextmanager
def bind_security_context(context: SecurityContext) -> Generator[SecurityContext, None, None]:
    """Temporarily bind an identity to the current execution.

    Args:
        context: The security context to bind.

    Yields:
        SecurityContext: The bound security context.

    Raises:
        TypeError: If the context is not a SecurityContext.
    """

    if not isinstance(context, SecurityContext):
        raise TypeError("context must be a SecurityContext.")

    # Store the identity and remember the previous context so we can restore it later
    reset_token = _current_context.set(context)

    try:
        yield context
    finally:
        # Restore the previous identity when this execution finishes
        _current_context.reset(reset_token)