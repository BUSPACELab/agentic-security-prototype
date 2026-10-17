"""Exceptions raised by the security system."""


class MissingSecurityContext(PermissionError):
    """Raised when a protected operation has no security context."""