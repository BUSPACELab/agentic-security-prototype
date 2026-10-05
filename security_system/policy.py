"""Policy interfaces required by the security system."""

from abc import ABC, abstractmethod
from pathlib import Path


class FileSystemPolicy(ABC):
    """Define application-specific filesystem permissions."""

    @abstractmethod
    def allows_read(self, actor_id: str, absolute_path: Path) -> bool:
        """Return whether the policy allows the actor to read the resource."""

        raise NotImplementedError

    @abstractmethod
    def allows_modify(self, actor_id: str, absolute_path: Path) -> bool:
        """Return whether the policy allows the actor to modify the resource."""

        raise NotImplementedError