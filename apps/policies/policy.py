"""Application-specific policies used by the security system."""

from pathlib import Path

from django.conf import settings

from security_system.helpers import is_path_within
from security_system.policy import FileSystemPolicy, DatabasePolicy, DatabaseReadRule, DatabaseModifyRule
from security_system.context import SecurityContext


class ApplicationFilePolicy(FileSystemPolicy):
    """Define filesystem permissions for this application."""

    def _user_root(self, actor_id: str) -> Path:
        """Return this application's filesystem root for a user."""

        return Path(settings.MCP_FILESYSTEM_ROOT) / "users" / actor_id

    def allows_read(self, actor_id: str, absolute_path: Path) -> bool:
        """Return whether the user may read the path."""

        # This application's users may read files inside their own upload directory
        user_root = self._user_root(actor_id)

        return is_path_within(absolute_path, user_root)

    def allows_modify(self, actor_id: str, absolute_path: Path) -> bool:
        """Return whether the user may modify the path."""

        # This application's users may modify files inside their own upload directory
        user_root = self._user_root(actor_id)
        deleted_root = Path(settings.MCP_FILESYSTEM_ROOT) / "_deleted" / actor_id

        return is_path_within(absolute_path, user_root) or is_path_within(absolute_path, deleted_root)

    
class ApplicationDatabasePolicy(DatabasePolicy):
    """Define database permissions for this application."""

    def read_rules(self, context: SecurityContext) -> tuple[DatabaseReadRule, ...]:
        """Return the permitted database read operations."""

        chat_context = context.attributes.get("chat_context")

        if chat_context == "file_chat":
            return (
                DatabaseReadRule(
                    table="files_uploadedfile",
                    columns=frozenset({"id", "title", "file", "created_at"}),
                    access_by="owner_id",
                ),
            )

        if chat_context == "profile_chat":
            return (
                DatabaseReadRule(
                    table="auth_user",
                    columns=frozenset({"id", "username", "email", "first_name", "last_name"}),
                    access_by="id",
                ),
            )

        return ()

    def modify_rules(self, context: SecurityContext) -> tuple[DatabaseModifyRule, ...]:
        """Return the permitted database modification operations."""

        chat_context = context.attributes.get("chat_context")

        if chat_context == "profile_chat":
            return (
                DatabaseModifyRule(
                    table="auth_user",
                    allowed_actions=frozenset({"UPDATE"}),
                    columns=frozenset({"username", "email", "first_name", "last_name"}),
                    filter_columns=frozenset({"id", "username", "email", "first_name", "last_name"}),
                    access_by="id",
                ),
            )

        return ()
