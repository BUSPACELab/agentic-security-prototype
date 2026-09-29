"""Security context propagation between local processes."""

import hmac
import json
import os
import secrets
import socket
import struct
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from threading import Thread


from .context import (
    Principal,
    SecurityContext,
    _get_security_context,
    _set_process_security_context,
)


_SOCKET_ENV = "SECURITY_SYSTEM_CONTEXT_SOCKET"
_TOKEN_ENV = "SECURITY_SYSTEM_CONTEXT_TOKEN"

_CONTEXT_VERSION = 1
_BOOTSTRAP_TIMEOUT = 30
_MAX_CONTEXT_BYTES = 16 * 1024
_MAX_TOKEN_BYTES = 512

_inherited_context_initialized = False


class InvalidProcessSecurityContext(PermissionError):
    """Raised when an inherited process context is invalid."""


def _serialize_context(context: SecurityContext) -> bytes:
    """Serialize one security context for process transfer."""

    payload = {
        "version": _CONTEXT_VERSION,
        "principal": {
            "subject": context.principal.subject,
            "issuer": context.principal.issuer,
        },
        "session_id": context.session_id,
    }

    encoded = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")

    if len(encoded) > _MAX_CONTEXT_BYTES:
        raise ValueError("Security context is too large.")

    return encoded


def _deserialize_context(data: bytes) -> SecurityContext:
    """Deserialize one transferred security context."""

    try:
        payload = json.loads(
            data.decode("utf-8")
        )

        if payload.get("version") != _CONTEXT_VERSION:
            raise ValueError("Unsupported security context version.")

        principal = payload["principal"]

        return SecurityContext(
            principal=Principal(
                subject=str(principal["subject"]),
                issuer=principal.get("issuer"),
            ),
            session_id=payload.get("session_id"),
        )

    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidProcessSecurityContext(
            "Invalid inherited security context."
        ) from exc


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    """Receive exactly the requested number of bytes."""

    data = bytearray()

    while len(data) < size:
        chunk = connection.recv(
            size - len(data)
        )

        if not chunk:
            raise InvalidProcessSecurityContext(
                "Process security channel closed unexpectedly."
            )

        data.extend(chunk)

    return bytes(data)


def _receive_token(connection: socket.socket) -> str:
    """Receive the child's one-time bootstrap token."""

    data = bytearray()

    while True:
        chunk = connection.recv(1)

        if not chunk:
            raise InvalidProcessSecurityContext(
                "Process security token was not received."
            )

        if chunk == b"\n":
            break

        data.extend(chunk)

        if len(data) > _MAX_TOKEN_BYTES:
            raise InvalidProcessSecurityContext(
                "Process security token is too large."
            )

    return data.decode("utf-8")


def _cleanup_bootstrap(socket_path: Path, directory: Path) -> None:
    """Remove the temporary IPC resources."""

    socket_path.unlink(
        missing_ok=True
    )

    try:
        directory.rmdir()
    except OSError:
        pass


def _serve_context_once(
    listener: socket.socket,
    socket_path: Path,
    directory: Path,
    expected_token: str,
    payload: bytes,
) -> None:
    """Send one context to the child that proves possession of the token."""

    deadline = (
        time.monotonic()
        + _BOOTSTRAP_TIMEOUT
    )

    try:
        while True:
            remaining = (
                deadline
                - time.monotonic()
            )

            if remaining <= 0:
                return

            listener.settimeout(
                remaining
            )

            try:
                connection, _ = listener.accept()
            except TimeoutError:
                return

            with connection:
                connection.settimeout(
                    remaining
                )

                try:
                    received_token = _receive_token(
                        connection
                    )
                except (
                    OSError,
                    TimeoutError,
                    UnicodeDecodeError,
                    InvalidProcessSecurityContext,
                ):
                    continue

                if not hmac.compare_digest(
                    received_token,
                    expected_token,
                ):
                    continue

                connection.sendall(
                    struct.pack(
                        "!I",
                        len(payload),
                    )
                )

                connection.sendall(
                    payload
                )

                return

    finally:
        listener.close()

        _cleanup_bootstrap(
            socket_path,
            directory,
        )


def child_process_environment(
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment that propagates the current context to one child."""

    environment = dict(
        os.environ
        if base_environment is None
        else base_environment
    )

    # Never forward a previous process bootstrap channel
    environment.pop(
        _SOCKET_ENV,
        None,
    )
    environment.pop(
        _TOKEN_ENV,
        None,
    )

    context = _get_security_context()

    # Processes may still be created without a security context.
    # Protected System operations in that child will fail closed.
    if context is None:
        return environment

    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        raise NotImplementedError(
            "Process security propagation currently requires POSIX Unix sockets."
        )

    payload = _serialize_context(
        context
    )

    directory = Path(
        tempfile.mkdtemp(
            prefix="security-system-"
        )
    )

    os.chmod(
        directory,
        0o700,
    )

    socket_path = (
        directory
        / "context.sock"
    )

    listener = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    try:
        listener.bind(
            str(socket_path)
        )

        os.chmod(
            socket_path,
            0o600,
        )

        listener.listen(1)

    except Exception:
        listener.close()

        _cleanup_bootstrap(
            socket_path,
            directory,
        )

        raise

    bootstrap_token = secrets.token_urlsafe(
        32
    )

    thread = Thread(
        target=_serve_context_once,
        args=(
            listener,
            socket_path,
            directory,
            bootstrap_token,
            payload,
        ),
        daemon=True,
        name="security-context-bootstrap",
    )

    thread.start()

    environment[_SOCKET_ENV] = str(
        socket_path
    )

    environment[_TOKEN_ENV] = (
        bootstrap_token
    )

    return environment


def initialize_inherited_process_context() -> None:
    """Initialize this process from an inherited security context."""

    global _inherited_context_initialized

    if _inherited_context_initialized:
        return

    socket_path = os.environ.pop(
        _SOCKET_ENV,
        None,
    )

    bootstrap_token = os.environ.pop(
        _TOKEN_ENV,
        None,
    )

    if socket_path is None and bootstrap_token is None:
        _inherited_context_initialized = True
        return

    if socket_path is None or bootstrap_token is None:
        raise InvalidProcessSecurityContext(
            "Incomplete inherited security context."
        )

    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        raise InvalidProcessSecurityContext(
            "Inherited process context requires POSIX Unix sockets."
        )

    connection = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )

    connection.settimeout(
        _BOOTSTRAP_TIMEOUT
    )

    try:
        connection.connect(
            socket_path
        )

        connection.sendall(
            bootstrap_token.encode(
                "utf-8"
            )
            + b"\n"
        )

        length_data = _receive_exact(
            connection,
            4,
        )

        payload_size = struct.unpack(
            "!I",
            length_data,
        )[0]

        if (
            payload_size <= 0
            or payload_size > _MAX_CONTEXT_BYTES
        ):
            raise InvalidProcessSecurityContext(
                "Invalid inherited security context size."
            )

        payload = _receive_exact(
            connection,
            payload_size,
        )

    except (OSError, TimeoutError) as exc:
        raise InvalidProcessSecurityContext(
            "Could not receive inherited security context."
        ) from exc

    finally:
        connection.close()

    context = _deserialize_context(
        payload
    )

    _set_process_security_context(
        context
    )

    print(
    "SYSTEM principal:",
    context.principal.subject,
    file=sys.stderr,
    )

    _inherited_context_initialized = True