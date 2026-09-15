"""Policy interfaces required by the security system."""

from abc import ABC, abstractmethod
from pathlib import Path


class FileSystemPolicy(ABC):
    """Define application-specific filesystem permissions."""

    @abstractmethod
    def allows_read(self, identity, absolute_path: Path) -> bool:
        """Return whether the policy allows the identity to read the resource."""

        raise NotImplementedError

    @abstractmethod
    def allows_modify(self, identity, absolute_path: Path) -> bool:
        """Return whether the policy allows the identity to modify the resource."""

        raise NotImplementedError