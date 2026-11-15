"""System module for enforcing application policies."""

from collections.abc import Mapping
from pathlib import Path
from sqlglot import exp
import os
import json

from .identity import IDENTITY_META_KEY, PUBLIC_KEY_ENV, issue_identity, public_key_pem
from .context import current_security_context
from .database import validate_sql
from .policy import FileSystemPolicy, DatabasePolicy

class System:
    """Enforce application policies before protected operations."""

    def __init__(self, policy: FileSystemPolicy, database_policy: DatabasePolicy | None = None, database=None):
        """Initialize the system with an application policy."""

        # Require applications to use the filesystem policy interface
        if not isinstance(policy, FileSystemPolicy):
            raise TypeError("policy must implement FileSystemPolicy.")

        if database_policy is not None and not isinstance(database_policy, DatabasePolicy):
            raise TypeError("database_policy must implement DatabasePolicy.")

        self.policy = policy
        self.database_policy = database_policy
        self.database = database

    def child_environment(self, base_environment: Mapping[str, str] | None = None) -> dict[str, str]:
        """Prepare the environment for a trusted local MCP child."""

        # Preserve the environment supplied by the application
        environment = dict(os.environ if base_environment is None else base_environment)

        # The child can verify signed identities without receiving the private key
        environment[PUBLIC_KEY_ENV] = public_key_pem()

        return environment

    def mcp_request_metadata(self) -> dict[str, str]:
        """Create signed identity metadata for the current MCP request."""

        # Get the identity already authenticated by the application
        context = current_security_context()

        # Sign the identity instead of trusting an arbitrary user ID
        return {IDENTITY_META_KEY: issue_identity(context)}

    def get_current_actor_id(self) -> str:
        """Return the authenticated actor for the current execution."""

        return current_security_context().principal.subject

    # -------------------- Filesystem access enforcement --------------------

    def _require_absolute_path(self, absolute_path) -> Path:
        """Require one concrete absolute filesystem resource."""

        path = Path(absolute_path)

        # The application must provide one concrete absolute resource
        if not path.is_absolute():
            raise ValueError("System requires an absolute path.")

        return path.resolve()

    def _authorize_read(self, absolute_path) -> Path:
        """Authorize the application's read policy."""

        # First enforce the System contract that resources are absolute
        path = self._require_absolute_path(absolute_path)

        # Get the trusted security context for the current execution
        context = current_security_context()

        # The application decides whether this context may read the resource
        if self.policy.allows_read(context, path) is not True:
            raise PermissionError("Access denied.")

        return path

    def _authorize_modify(self, absolute_path) -> Path:
        """Authorize the application's modify policy."""

        # First enforce the System contract that resources are absolute
        path = self._require_absolute_path(absolute_path)

        # Get the trusted security context for the current execution
        context = current_security_context()

        # The application decides whether this context may modify the resource
        if self.policy.allows_modify(context, path) is not True:
            raise PermissionError("Access denied.")

        return path

    def read_text(self, absolute_path) -> str:
        """Read text only after the application policy allows it."""

        # Authorize READ before checking the resource type or accessing it
        path = self._authorize_read(absolute_path)

        # read_text only operates on existing regular files
        if not path.is_file():
            raise FileNotFoundError("Path is not a readable regular file.")

        # Perform the protected operation only after authorization succeeds
        return path.read_text(encoding="utf-8")

    def list(self, absolute_path, recursive: bool = False) -> list[Path]:
        """List directory entries the application policy allows the context to read."""

        # Authorize READ before checking the resource type or accessing it
        path = self._authorize_read(absolute_path)

        # list only operates on existing directories
        if not path.is_dir():
            raise NotADirectoryError("Path is not a readable directory.")

        # Use the current context when filtering entries
        context = current_security_context()

        # Helper used to check whether an entry may be exposed
        def is_readable(entry: Path) -> bool:
            return self.policy.allows_read(context, entry.resolve()) is True

        readable_entries = []

        # List only the direct entries when recursion is not requested
        if not recursive:
            for entry in path.iterdir():
                if is_readable(entry):
                    readable_entries.append(entry)

            return sorted(
                readable_entries,
                key=lambda item: item.as_posix().lower(),
            )

        # Walk through the directory tree one directory at a time
        for current_directory, directory_names, file_names in path.walk():
            allowed_directory_names = []

            # Add readable directories and allow the walk to enter them
            for name in directory_names:
                entry = current_directory / name

                if is_readable(entry):
                    readable_entries.append(entry)
                    allowed_directory_names.append(name)

            # Prevent the walk from entering directories that are not readable
            directory_names[:] = allowed_directory_names

            # Add readable files from the current directory
            for name in file_names:
                entry = current_directory / name

                if is_readable(entry):
                    readable_entries.append(entry)

        return sorted(
            readable_entries,
            key=lambda item: item.as_posix().lower(),
        )
    def write_text(self, absolute_path, data: str) -> int:
        """Write text only after the application policy allows it."""

        # Authorize MODIFY before changing the filesystem
        path = self._authorize_modify(absolute_path)

        # Perform the protected operation only after authorization succeeds
        return path.write_text(data, encoding="utf-8")

    def remove_file(self, absolute_path) -> None:
        """Remove a file only after the application policy allows it."""

        # Authorize MODIFY before changing the filesystem
        path = self._authorize_modify(absolute_path)

        # Perform the protected operation only after authorization succeeds
        path.unlink()

    def copy_file(self, source_path, destination_path) -> None:
        """Copy a file only after the application policy allows it."""

        # Authorize both resources before accessing or changing the filesystem
        source = self._authorize_read(source_path)
        destination = self._authorize_modify(destination_path)

        # Ensure the source is a readable regular file before copying
        if not source.is_file():
            raise FileNotFoundError("Path is not a readable regular file.")

        # Perform the protected operation only after authorization succeeds
        source.copy(destination)

    def move_file(self, source_path, destination_path) -> None:
        """Move a file only after the application policy allows it."""

        # Authorize both resources before accessing or changing the filesystem
        source = self._authorize_read(source_path)
        source = self._authorize_modify(source_path)
        destination = self._authorize_modify(destination_path)

        # Ensure the source is a readable regular file before moving
        if not source.is_file():
            raise FileNotFoundError("Path is not a readable regular file.")

        # Ensure the destination is a writable directory before moving
        self.mkdir(destination.parent, parents=True, exist_ok=True)

        # Perform the protected operation only after authorization succeeds
        source.move(destination)

    def mkdir(self, absolute_path, parents: bool = False, exist_ok: bool = False) -> None:
        """Create a directory only after authorization."""

        # Authorize the resource before changing the filesystem
        path = self._authorize_modify(absolute_path)

        # Perform the protected operation only after authorization succeeds
        path.mkdir(parents=parents, exist_ok=exist_ok)


    # -------------------- Database access enforcement --------------------

    def authorize_sql(self, query: str) -> str:
        """Check database permissions before running SQL."""

        if self.database_policy is None:
            raise PermissionError("Database access denied.")

        # Get the authenticated context and validate the SQL
        context = current_security_context()
        statement = validate_sql(query)
        reading = isinstance(statement, exp.Select)
        table = statement.find(exp.Table).name.lower()

        # Get the policy for this table
        rules = self.database_policy.read_rules(context) if reading else self.database_policy.modify_rules(context)
        matches = [rule for rule in rules if rule.table.lower() == table]

        if len(matches) != 1:
            raise PermissionError("Table access denied.")

        rule = matches[0]
        allowed_columns = {column.lower() for column in rule.columns}

        if reading:
            if not allowed_columns:
                raise PermissionError("No readable columns.")

            # Replace SELECT * with the columns the user can read
            if len(statement.expressions) == 1 and isinstance(statement.expressions[0], exp.Star):
                statement.set("expressions", [exp.column(column, quoted=True) for column in sorted(rule.columns)])

            # Check for wildcard (*) access
            if any(not isinstance(star.parent, exp.Count) for star in statement.find_all(exp.Star)):
                raise PermissionError("Wildcard denied.")

            columns = statement.find_all(exp.Column)


        else:
            if "UPDATE" not in rule.allowed_actions:
                raise PermissionError("UPDATE denied.")

            # Check which columns can be modified
            if any(item.this.name.lower() not in allowed_columns for item in statement.expressions):
                raise PermissionError("Column modification denied.")

            # Check which columns can be used in WHERE
            allowed_columns = {column.lower() for column in rule.filter_columns}

            # Get the actual columns used in WHERE
            where = statement.args.get("where")
            columns = where.find_all(exp.Column) if where is not None else ()

        # Check allowed columns and ORDER BY aliases
        aliases = {item.alias.lower() for item in statement.expressions if item.alias} if reading else set()

        for column in columns:
            allowed_alias = not column.table and column.name.lower() in aliases and isinstance(column.parent, exp.Ordered)
            if column.name.lower() not in allowed_columns and not allowed_alias:
                raise PermissionError("Column access denied.")

        # Limit the query to the current user's records
        if rule.access_by is not None:
            condition = exp.EQ(this=exp.column(rule.access_by, table=statement.find(exp.Table).alias or None, quoted=True), expression=exp.Literal.string(context.principal.subject))
            statement = statement.where(condition, append=True)


        # Generate the authorized SQL without comments
        return statement.sql(dialect="sqlite", comments=False)

    def execute_sql(self, query: str) -> str:
        """Execute SQL after checking permissions."""

        if self.database is None:
            raise PermissionError("Database access denied.")

        query = self.authorize_sql(query)

        # Run the authorized query
        cursor = self.database.cursor()

        try:
            cursor.execute(query)

            if cursor.description:
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchmany(51)
                return json.dumps({"columns": columns, "rows": rows[:50], "truncated": len(rows) > 50}, default=str)

            self.database.commit()
            return f"SQL executed. Rows affected: {cursor.rowcount}"

        finally:
            cursor.close()

    def database_schema(self) -> str:
        """Return the tables and columns allowed by the policy."""

        if self.database_policy is None:
            raise PermissionError("Database access denied.")

        context = current_security_context()
        lines = []

        for rule in self.database_policy.read_rules(context):
            lines.append(f"{rule.table} | READ: {', '.join(sorted(rule.columns))}")

        for rule in self.database_policy.modify_rules(context):
            lines.append(f"{rule.table} | {', '.join(sorted(rule.allowed_actions))}: {', '.join(sorted(rule.columns))} | WHERE: {', '.join(sorted(rule.filter_columns))}")

        return "\n".join(lines) or "No database access."
