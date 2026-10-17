
"""Issue and verify signed identities for MCP requests."""

import os
import time
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from filelock import FileLock

from .context import MissingSecurityContext, Principal, SecurityContext

# Metadata keys
IDENTITY_META_KEY = "agentic-security.identity"
KEY_FILE_ENV = "SECURITY_SYSTEM_KEY_FILE"
PUBLIC_KEY_ENV = "SECURITY_SYSTEM_PUBLIC_KEY"

# Identity signing
ISSUER = "security-system"
AUDIENCE = "security-system:mcp"
# Token lifetime in seconds (short-lived for security) which means the token is valid for 1 minute after issuance.
TOKEN_LIFETIME = 60

# Local key storage
_local_public_key: Ed25519PublicKey | None = None


@lru_cache(maxsize=1) # Cache the signing key so every worker uses the same identity from in-memory storage
def _signing_key() -> Ed25519PrivateKey:
    """Load or create the application's persistent signing key.

    Returns:
        Ed25519PrivateKey: The key used to sign authenticated identities.

    Raises:
        NotImplementedError: If automatic local key storage is unsupported.
        PermissionError: If key storage is not private.
        TypeError: If the stored key uses the wrong algorithm.
    """

    global _local_public_key

    # Automatic local key protection currently uses POSIX file permissions - could add Windows support later if needed
    if os.name != "posix":
        raise NotImplementedError("Automatic key storage currently requires POSIX.")

    # Use a private local directory unless the deployment chooses a key location
    key_path = Path(os.environ.get(KEY_FILE_ENV, ".security_system/identity.pem")).expanduser().absolute()
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Require the directory to belong to this process's OS user
    directory_info = key_path.parent.stat()

    if directory_info.st_uid != os.getuid() or directory_info.st_mode & 0o077:
        raise PermissionError("Signing key directory must be private.")

    # Prevent multiple application workers from creating different keys
    with FileLock(str(key_path) + ".lock"):
        if key_path.is_symlink():
            raise PermissionError("Signing key cannot be a symbolic link.")

        if not key_path.exists():
            # Generate a private key using the cryptography library
            private_key = Ed25519PrivateKey.generate()

            # Convert the key to the standard PEM format
            key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM, # Use PEM encoding for compatibility
                format=serialization.PrivateFormat.PKCS8, # Use PKCS#8 format for private keys
                encryption_algorithm=serialization.NoEncryption(), # Use no encryption for simplicity, but could be changed to a password-based encryption if needed
            )

            temporary_path = None

            try:
                # Create a private temporary file so incomplete writes are never installed
                with NamedTemporaryFile(mode="wb", dir=key_path.parent, delete=False) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    temporary_file.write(key_bytes)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())

                # Install the complete key using an atomic filesystem replacement
                os.replace(temporary_path, key_path)
            finally:
                # Clean up the temporary file if creation or replacement fails
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

        # Never trust a signing key that is not a regular file with private permissions
        if not key_path.is_file():
            raise PermissionError("Signing key must be a regular file.")

        file_info = key_path.stat()

        if file_info.st_uid != os.getuid() or file_info.st_mode & 0o077:
            raise PermissionError("Signing key file must be private.")

        # Load the existing key so every worker uses the same signing identity
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Signing key must use Ed25519.")

    # Remember the matching public key for trusted same-process execution
    _local_public_key = private_key.public_key()

    return private_key


def public_key_pem() -> str:
    """Return the public key for MCP identity verification.

    Returns:
        str: The public verification key in PEM format.
    """

    # The MCP server needs only the public key to verify identities, so we can expose it without revealing the private signing key
    public_key = _signing_key().public_key()

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return public_bytes.decode("ascii")


def issue_identity(context: SecurityContext) -> str:
    """Sign the authenticated identity of the current application request.

    Args:
        context: The security context established by a trusted application.

    Returns:
        str: A signed identity token with a short expiration time.

    Raises:
        TypeError: If the supplied context is invalid.
    """

    if not isinstance(context, SecurityContext):
        raise TypeError("context must be a SecurityContext.")

    now = int(time.time())

    # Include the identity and the restrictions the receiver must verify
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": context.principal.subject,
        "actor_issuer": context.principal.issuer,
        "iat": now,
        "exp": now + TOKEN_LIFETIME,
    }

    # Sign the claims using the trusted application's private key
    return jwt.encode(claims, _signing_key(), algorithm="EdDSA")


def verify_identity(token: str) -> SecurityContext:
    """Verify an MCP identity token and recover its authenticated principal.

    Args:
        token: The signed identity received with an MCP request.

    Returns:
        SecurityContext: The verified identity for this request.

    Raises:
        MissingSecurityContext: If no trusted public key is available.
        PermissionError: If the token is invalid or expired.
    """

    # Reject missing or unexpectedly large identity tokens
    if not isinstance(token, str) or len(token) > 4096:
        raise PermissionError("Invalid MCP identity.")

    # A separately launched MCP process receives its public key from the launcher
    if PUBLIC_KEY_ENV in os.environ:
        public_key = os.environ[PUBLIC_KEY_ENV]
    else:
        # An in-process MCP execution can use an already initialized local key
        public_key = _local_public_key

    if not public_key:
        raise MissingSecurityContext("No trusted public key is available.")

    try:
        # Verify the signature, allowed algorithm, issuer, audience and timestamps
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["iss", "aud", "sub", "iat", "exp"]},
            leeway=3,
        )

        # Ensure the token has the expected short lifetime
        issued_at = claims["iat"]
        expires_at = claims["exp"]

        if type(issued_at) is not int or type(expires_at) is not int:
            raise ValueError("Invalid identity timestamps.")

        if not 0 < expires_at - issued_at <= TOKEN_LIFETIME:
            raise ValueError("Invalid identity lifetime.")

        # Require a real principal rather than accepting arbitrary JWT content
        subject = claims["sub"]
        actor_issuer = claims.get("actor_issuer")

        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("Invalid identity subject.")

        if actor_issuer is not None and not isinstance(actor_issuer, str):
            raise ValueError("Invalid identity issuer.")

        return SecurityContext(principal=Principal(subject=subject, issuer=actor_issuer))

    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
        raise PermissionError("Invalid MCP identity.") from error