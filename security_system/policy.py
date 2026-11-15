"""Policy interfaces required by the security system."""

from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass

from security_system.context import SecurityContext


#------------------------------------ Filesystem policy -----------------------------------

class FileSystemPolicy(ABC):
    """Define application-specific filesystem permissions."""

    @abstractmethod
    def allows_read(self, context: SecurityContext, absolute_path: Path) -> bool:
        """Return whether the policy allows the actor to read the resource."""

        raise NotImplementedError

    @abstractmethod
    def allows_modify(self, context: SecurityContext, absolute_path: Path) -> bool:
        """Return whether the policy allows the actor to modify the resource."""

        raise NotImplementedError


# ----------------------------------- Database policy -----------------------------------

@dataclass(frozen=True)
class DatabaseReadRule:
    """Define permissions for reading a database table."""

    table: str
    columns: frozenset[str]
    access_by: str | None


@dataclass(frozen=True)
class DatabaseModifyRule:
    """Define permissions for modifying a database table."""

    table: str
    allowed_actions: frozenset[str]
    columns: frozenset[str]
    filter_columns: frozenset[str]
    access_by: str | None


class DatabasePolicy(ABC):
    """Define application-specific database permissions."""

    @abstractmethod
    def read_rules(self, context: SecurityContext) -> tuple[DatabaseReadRule, ...]:
        """Return the permitted database read operations."""

        raise NotImplementedError

    @abstractmethod
    def modify_rules(self, context: SecurityContext) -> tuple[DatabaseModifyRule, ...]:
        """Return the permitted database modification operations."""

        raise NotImplementedError
