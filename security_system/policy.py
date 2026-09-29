"""Policy interfaces required by the security system."""

from abc import ABC, abstractmethod
from pathlib import Path

from .context import SecurityContext


class FileSystemPolicy(ABC):
    """Define application-specific filesystem permissions."""

    @abstractmethod
    def allows_read(self, context: SecurityContext, absolute_path: Path) -> bool:
        """Return whether the policy allows the context to read the resource."""

        raise NotImplementedError

    @abstractmethod
    def allows_modify(self, context: SecurityContext, absolute_path: Path) -> bool:
        """Return whether the policy allows the context to modify the resource."""

        raise NotImplementedError