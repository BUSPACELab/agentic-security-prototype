"""System module for enforcing application policies."""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path

from .context import Principal, SecurityContext, bind_security_context, current_security_context
from .policy import FileSystemPolicy
from .process import child_process_environment, initialize_inherited_process_context


class System:
    """Enforce application policies before protected operations."""

    def __init__(self, policy: FileSystemPolicy):
        """Initialize the system with an application policy."""

        # Require applications to use the filesystem policy interface
        if not isinstance(policy, FileSystemPolicy):
            raise TypeError("policy must implement FileSystemPolicy.")

        self.policy = policy

        # Load a security context inherited from a parent process, if one exists
        initialize_inherited_process_context()

    def as_principal(
    self,
    subject: int | str,
    session_id: str | None = None,
    issuer: str | None = None,
    ) -> AbstractContextManager[SecurityContext]:
        """Bind one authenticated principal to the current execution."""

        context = SecurityContext(
            principal=Principal(
                subject=str(subject),
                issuer=issuer,
            ),
            session_id=session_id,
        )

        return bind_security_context(
            context
        )


    def child_environment(
        self,
        base_environment: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Prepare one child process to inherit the current security context."""

        return child_process_environment(
            base_environment
        )

    def _require_absolute_path(self, absolute_path) -> Path:
        """Require one concrete absolute filesystem resource."""

        path = Path(absolute_path)

        # The application must provide one concrete absolute resource
        if not path.is_absolute():
            raise ValueError("System requires an absolute path.")

        return path

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
            return self.policy.allows_read(context, entry) is True

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

        # Perform the protected operation only after authorization succeeds
        source.move(destination)
