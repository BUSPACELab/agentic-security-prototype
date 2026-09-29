"""Security context used by protected operations."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


class MissingSecurityContext(PermissionError):
    """Raised when a protected operation has no security context."""


@dataclass(frozen=True)
class Principal:
    """Authenticated actor represented independently of any framework."""

    subject: str
    issuer: str | None = None

    def __post_init__(self):
        subject = str(self.subject).strip()

        if not subject:
            raise ValueError("Principal subject is required.")

        object.__setattr__(self, "subject", subject)


@dataclass(frozen=True)
class SecurityContext:
    """Security information associated with the current execution."""

    principal: Principal
    session_id: str | None = None


_current_context: ContextVar[SecurityContext | None] = ContextVar(
    "security_system_context",
    default=None,
)

_process_context: SecurityContext | None = None


def _get_security_context() -> SecurityContext | None:
    """Return the current execution or inherited process context."""

    context = _current_context.get()

    if context is not None:
        return context

    return _process_context


def current_security_context() -> SecurityContext:
    """Return the current security context or fail closed."""

    context = _get_security_context()

    if context is None:
        raise MissingSecurityContext("A security context is required.")

    return context


def _set_process_security_context(context: SecurityContext) -> None:
    """Set the inherited context for this process."""

    global _process_context

    if not isinstance(context, SecurityContext):
        raise TypeError("context must be a SecurityContext.")

    if _process_context is not None and _process_context != context:
        raise RuntimeError("Process security context is already established.")

    _process_context = context


@contextmanager
def bind_security_context(context: SecurityContext) -> Generator[SecurityContext, None, None]:
    """Bind a security context to the current execution."""

    if not isinstance(context, SecurityContext):
        raise TypeError("context must be a SecurityContext.")

    if _process_context is not None and _process_context != context:
        raise RuntimeError(
            "An inherited process security context cannot be replaced."
        )

    token = _current_context.set(context)

    try:
        yield context
    finally:
        _current_context.reset(token)