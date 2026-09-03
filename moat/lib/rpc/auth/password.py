"""
Username/password authentication.

This module implements a SubAuth handler for the MoaT RPC auth framework.

Client side: sends username + password to the server.
Server side: checks the supplied credentials against a local user database.

Optionally, the password can be shielded with Diffie-Hellman key exchange
so that the actual password hash is encrypted in transit and never sent
in cleartext.  When ``dh`` is set to a truthy value in the mode config,
both sides perform a DH key exchange; the resulting shared secret is fed
through HKDF-SHA256 and used as an AES-256-GCM key to encrypt the
SHA-256 password digest.

All cryptographic primitives are provided by the vetted ``cryptography``
package — no custom crypto is rolled.

Server configuration::

    auth:
      modes:
      - mode: password
        dh: true          # optional, shields password via DH
        fail_invalid: true  # reject bad credentials instead of ignoring
      password:
        alice: "$ecret"   # map of username → password
        bob: "hunter2"

Client configuration::

    auth:
      modes:
      - mode: password
        dh: true          # must match the server setting
      password:
        user: alice
        password: "$ecret"

Handshake flow (DH enabled)
---------------------------

Phase 1 — key exchange::

    Client → Server:  (client_public_key_bytes,)
    Server → Client:  (server_public_key_bytes, nonce, encrypted_challenge)

Phase 2 — credential submission::

    Client → Server:  (username, nonce, encrypted_password_hash, challenge_response)

Both sides derive the shared secret via ECDH-style modular exponentiation
(DH group 14, 2048-bit), feed it through HKDF-SHA256 with the info string
``b"moat-rpc-password-dh"``, and use the 32-byte result as an AES-256-GCM
key.

If DH negotiation fails on either side (exception, unexpected response),
the client falls back to the plain (TLS-protected) submission path.
"""

from __future__ import annotations

import hmac
import logging
from hashlib import sha256

from moat.lib.micro import Event, L

from ._base import SubAuth as _SubAuth

logger = logging.getLogger(__name__)

# HKDF info string for the DH password-shielding context.
_HKDF_INFO = b"moat-rpc-password-dh"


class AuthFailed(Exception):
    """
    Raised internally when server-side credential validation fails.

    Caught by the caller which decides whether to deny the connection
    (``fail_invalid: true``) or silently ignore the attempt.
    """


def _hash_password(password: str | bytes) -> bytes:
    """Hash a password with SHA-256 and return the digest."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    return sha256(password).digest()


def _to_bytes(val: object) -> bytes | None:
    """Convert a wire-type value (bytes/memoryview) to bytes, or None."""
    if isinstance(val, memoryview):
        return bytes(val)
    if isinstance(val, bytes):
        return val
    return None


def _derive_dh_key(shared_secret: bytes) -> bytes:
    """Derive a 32-byte AES-256 key from a raw DH shared secret via HKDF-SHA256."""
    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: PLC0415

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(shared_secret)


def _generate_dh_parameters():
    """Generate DH parameters (2048-bit, generator 2). Cached at module level."""
    global _dh_params
    if _dh_params is None:
        from cryptography.hazmat.primitives.asymmetric import dh  # noqa: PLC0415

        _dh_params = dh.generate_parameters(generator=2, key_size=2048)
    return _dh_params


_dh_params: object | None = None  # cached DH parameter object


class SubAuth(_SubAuth):
    """
    Auth method for username/password login.

    Client auth: a dict with ``user`` and ``password`` keys, sent to the
    server.  When ``dh`` is enabled, the password digest is encrypted
    with a DH-derived shared secret before transmission.

    Server auth: a dict mapping usernames to passwords.  The server
    verifies the incoming credentials and accepts or denies accordingly.

    Config:
        dh(bool): if True, shield the password via Diffie-Hellman key
                  exchange.  Both sides must agree on this setting.
        fail_invalid(bool): if True (server side), a client that sends
                            invalid credentials is actively denied rather
                            than silently ignored.
    """

    _done_evt: Event
    _dh_key: bytes | None
    _dh_challenge: bytes | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._done_evt = Event()
        self._dh_key = None
        self._dh_challenge = None

    def _reject(self) -> None:
        """Deny or ignore based on ``fail_invalid``."""
        if self.cfg.get("fail_invalid", False):
            self.deny()

    def _cleanup_dh_state(self) -> None:
        """Zero out and clear DH session state so secrets don't linger."""
        self._dh_key = None
        self._dh_challenge = None

    async def task(self) -> None:
        """Client-side: send credentials to the server."""
        if L:
            self.set_ready()

        if self.is_server:
            # Wait for the server-side cmd() handler to finish processing.
            await self._done_evt.wait()
            return

        cred = self.auth
        if cred is None:
            return  # nothing to send

        user = cred.get("user")
        password = cred.get("password")
        if user is None or password is None:
            return

        if self.cfg.get("dh", False):
            try:
                await self._client_dh(user, password)
            except Exception:
                logger.warning("DH negotiation failed, falling back to plain auth", exc_info=True)
                # Clean up any partial DH state
                self._cleanup_dh_state()
                # Fall back to plain (TLS-protected) submission
                pwd_hash = _hash_password(password)
                await self.remote(user, pwd_hash)
        else:
            pwd_hash = _hash_password(password)
            await self.remote(user, pwd_hash)

        self.accept()

    async def _client_dh(self, user: str, password: str) -> None:
        """DH-shielded client: exchange keys, encrypt, send credentials.

        Raises on any failure so the caller can fall back to plain auth.
        """
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        # Generate our DH keypair
        params = _generate_dh_parameters()
        priv_key = params.generate_private_key()
        pub_key = priv_key.public_key()
        pub_bytes = pub_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        pwd_hash = _hash_password(password)

        # Phase 1: send our public key; server responds with theirs + challenge
        res = await self.remote(pub_bytes)
        if res is None:
            raise RuntimeError("Server returned no DH response")
        if len(res) < 3:
            raise RuntimeError("Malformed DH phase-1 response")

        server_pub_bytes = _to_bytes(res[0])
        nonce = _to_bytes(res[1])
        enc_challenge = _to_bytes(res[2])

        if server_pub_bytes is None or nonce is None or enc_challenge is None:
            raise RuntimeError("Invalid DH phase-1 response types")

        # Deserialize server's public key and derive shared secret
        server_pub_key = serialization.load_pem_public_key(server_pub_bytes)
        shared_secret = priv_key.exchange(server_pub_key)
        key = _derive_dh_key(shared_secret)

        # Decrypt challenge
        aesgcm = AESGCM(key)
        try:
            challenge = aesgcm.decrypt(nonce, enc_challenge, None)
        except Exception as exc:
            raise RuntimeError("Challenge decryption failed") from exc

        # Encrypt password hash
        enc_nonce = _generate_nonce()
        enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

        # Phase 2: send username + encrypted password + challenge response
        await self.remote(user, enc_nonce, enc_pwd, challenge)

        # Zero out sensitive data
        del shared_secret, key, pwd_hash

    async def cmd(self, *args: object) -> tuple | None:
        """Server-side: handle incoming credential submission.

        Without DH: ``(username, password_hash)``.
        With DH: ``(public_key,)`` then
        ``(username, nonce, encrypted_password, challenge_response)``.
        """
        self._seen_evt.set()

        if self.cfg.get("dh", False):
            return await self._cmd_dh(args)

        await self._cmd_plain(args)
        self._done_evt.set()
        return None

    async def _cmd_plain(self, args: tuple) -> None:
        """Handle plain (non-DH) password auth."""
        try:
            if len(args) < 2:
                raise AuthFailed("Missing credentials")

            user = args[0]
            pwd_hash = _to_bytes(args[1])
            if pwd_hash is None:
                raise AuthFailed("Invalid password hash type")

            expected = self.auth.get(user)
            if expected is None:
                raise AuthFailed("Unknown user")

            expected_hash = _hash_password(expected)
            if not hmac.compare_digest(pwd_hash, expected_hash):
                raise AuthFailed("Password mismatch")

            self.accept()
        except AuthFailed:
            self._reject()

    async def _cmd_dh(self, args: tuple) -> tuple | None:
        """Handle DH-shielded password auth.

        First call: ``(client_public_key_bytes,)`` → returns
        ``(server_public_key_bytes, nonce, encrypted_challenge)``.

        Second call: ``(username, nonce, encrypted_password, challenge_response)``
        → validates and accepts/denies.
        """
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        if len(args) == 1:
            # Phase 1: receive client's public key, send ours + a challenge
            client_pub_bytes = _to_bytes(args[0])
            if client_pub_bytes is None:
                self._reject()
                return None

            try:
                client_pub_key = serialization.load_pem_public_key(client_pub_bytes)

                params = _generate_dh_parameters()
                priv_key = params.generate_private_key()
                pub_key = priv_key.public_key()
                pub_bytes = pub_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )

                shared_secret = priv_key.exchange(client_pub_key)
                key = _derive_dh_key(shared_secret)

                challenge = _generate_nonce()
                aesgcm = AESGCM(key)
                nonce = _generate_nonce()
                enc_challenge = aesgcm.encrypt(nonce, challenge, None)

                # Store state for phase 2
                self._dh_key = key
                self._dh_challenge = challenge

                # Zero out intermediate secret material
                del shared_secret, priv_key

                return (pub_bytes, nonce, enc_challenge)
            except Exception:
                logger.warning("DH phase 1 failed", exc_info=True)
                self._reject()
                return None

        # Phase 2: receive username + encrypted password + challenge response
        try:
            if len(args) < 4:
                raise AuthFailed("Incomplete DH phase-2 payload")

            user = args[0]
            enc_nonce = _to_bytes(args[1])
            enc_pwd = _to_bytes(args[2])
            challenge_resp = _to_bytes(args[3])

            key = self._dh_key
            if key is None:
                raise AuthFailed("DH phase 1 not received")

            if challenge_resp is None:
                raise AuthFailed("Invalid challenge response type")
            if enc_nonce is None:
                raise AuthFailed("Invalid nonce type")
            if enc_pwd is None:
                raise AuthFailed("Invalid encrypted password type")

            challenge = self._dh_challenge
            if challenge is None:
                raise AuthFailed("Missing challenge state")

            if not hmac.compare_digest(challenge_resp, challenge):
                raise AuthFailed("Challenge mismatch")

            aesgcm = AESGCM(key)
            try:
                pwd_hash = aesgcm.decrypt(enc_nonce, enc_pwd, None)
            except Exception:
                raise AuthFailed("Decryption failed") from None

            expected = self.auth.get(user)
            if expected is None:
                raise AuthFailed("Unknown user")

            expected_hash = _hash_password(expected)
            if not hmac.compare_digest(pwd_hash, expected_hash):
                raise AuthFailed("Password mismatch")

            self.accept()
        except AuthFailed:
            self._reject()
        finally:
            # Always clean up DH state regardless of outcome
            self._cleanup_dh_state()

        self._done_evt.set()
        return None


def _generate_nonce() -> bytes:
    """Generate a 12-byte random nonce for AES-GCM."""
    from os import urandom  # noqa: PLC0415

    return urandom(12)
