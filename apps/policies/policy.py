"""Application-specific policies used by the security system."""

from pathlib import Path

from django.conf import settings

from security_system.helpers import is_path_within
from security_system.policy import FileSystemPolicy


class ApplicationFilePolicy(FileSystemPolicy):
    """Define filesystem permissions for this application."""

    def _user_root(self, identity) -> Path:
        """Return this application's filesystem root for a user."""

        return Path(settings.MCP_FILESYSTEM_ROOT) / "users" / str(identity)

    def allows_read(self, identity, absolute_path: Path) -> bool:
        """Return whether the user may read the path."""

        # This application's users may read files inside their own upload directory
        user_root = self._user_root(identity)

        return is_path_within(absolute_path, user_root)

    def allows_modify(self, identity, absolute_path: Path) -> bool:
        """Return whether the user may modify the path."""

        # This application's users may modify files inside their own upload directory
        user_root = self._user_root(identity)
        deleted_root = Path(settings.MCP_FILESYSTEM_ROOT) / "_deleted" / str(identity)

        return is_path_within(absolute_path, user_root) or is_path_within(absolute_path, deleted_root)