"""System module for enforcing application policies."""

from pathlib import Path
import shutil

from .policy import FileSystemPolicy


class System:
    """Enforce application policies before protected operations."""

    def __init__(self, policy: FileSystemPolicy):
        """Initialize the system with an application policy."""

        # Require applications to use the filesystem policy interface
        if not isinstance(policy, FileSystemPolicy):
            raise TypeError("policy must implement FileSystemPolicy.")

        self.policy = policy

    def _require_absolute_path(self, absolute_path) -> Path:
        """Require one concrete absolute filesystem resource."""

        path = Path(absolute_path)

        # The application must provide one concrete absolute resource
        if not path.is_absolute():
            raise ValueError("System requires an absolute path.")

        return path

    def _authorize_read(self, absolute_path, identity) -> Path:
        """Authorize the application's read policy."""

        # First enforce the System contract that resources are absolute
        path = self._require_absolute_path(absolute_path)

        # The application decides whether this identity may read the resource
        if self.policy.allows_read(identity, path) is not True:
            raise PermissionError("Access denied.")

        return path

    def _authorize_modify(self, absolute_path, identity) -> Path:
        """Authorize the application's modify policy."""

        # First enforce the System contract that resources are absolute
        path = self._require_absolute_path(absolute_path)

        # The application decides whether this identity may modify the resource
        if self.policy.allows_modify(identity, path) is not True:
            raise PermissionError("Access denied.")

        return path

    def read_text(self, absolute_path, identity) -> str:
        """Read text only after the application policy allows it."""

        # Authorize READ before checking the resource type or accessing it
        path = self._authorize_read(absolute_path, identity)

        # read_text only operates on existing regular files
        if not path.is_file():
            raise FileNotFoundError("Path is not a readable regular file.")

        # Perform the protected operation only after authorization succeeds
        return path.read_text(encoding="utf-8")

    def list(self, absolute_path, identity, recursive: bool = False) -> list[Path]:
        """List directory entries the application policy allows the identity to read."""

        # Authorize READ before checking the resource type or accessing it
        path = self._authorize_read(absolute_path, identity)

        # list only operates on existing directories
        if not path.is_dir():
            raise NotADirectoryError("Path is not a readable directory.")

        # Helper used to check whether an entry may be exposed
        def is_readable(entry: Path) -> bool:
            return self.policy.allows_read(identity, entry) is True

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

    def write_text(self, absolute_path, identity, data: str) -> int:
        """Write text only after the application policy allows it."""

        # Authorize MODIFY before changing the filesystem
        path = self._authorize_modify(absolute_path, identity)

        # Perform the protected operation only after authorization succeeds
        return path.write_text(data, encoding="utf-8")

    def remove_file(self, absolute_path, identity) -> None:
        """Remove a file only after the application policy allows it."""

        # Authorize MODIFY before changing the filesystem
        path = self._authorize_modify(absolute_path, identity)

        # Perform the protected operation only after authorization succeeds
        path.unlink()

    def copy_file(self, source_path, destination_path, identity) -> None:
        """Copy a file only after the application policy allows it."""

        # Authorize both resources before accessing or changing the filesystem
        # The source must be readable and the destination must be modifiable
        source = self._authorize_read(source_path, identity)
        destination = self._authorize_modify(destination_path, identity)

        # Ensure the source is a readable regular file before copying
        if not source.is_file():
            raise FileNotFoundError("Path is not a readable regular file.")

        # Perform the protected operation only after authorization succeeds
        shutil.copyfile(source, destination)
