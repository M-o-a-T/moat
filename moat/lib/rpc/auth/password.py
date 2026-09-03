"""
Username/password authentication.

This module implements a SubAuth handler for the MoaT RPC auth framework.

Client side: sends username + password to the server.
Server side: checks the supplied credentials against a local user database.

Optionally, the password can be shielded with Diffie-Hellman key exchange
so that the actual password hash is encrypted in transit and never sent
in cleartext.  When ``dh`` is set to a truthy value in the mode config,
both sides perform a DH key exchange; the resulting shared secret is used
as a symmetric key (via :class:`nacl.secret.SecretBox`) to encrypt the
SHA-256 password digest.

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
"""

from __future__ import annotations

import hmac
from hashlib import sha256

from moat.lib.micro import Event, L

from ._base import SubAuth as _SubAuth


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._done_evt = Event()

    def _reject(self) -> None:
        """Deny or ignore based on ``fail_invalid``."""
        if self.cfg.get("fail_invalid", False):
            self.deny()

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
            await self._client_dh(user, password)
        else:
            pwd_hash = _hash_password(password)
            await self.remote(user, pwd_hash)

        self.accept()

    async def _client_dh(self, user: str, password: str) -> None:
        """DH-shielded client: exchange keys, encrypt, send credentials."""
        import nacl.secret  # noqa: PLC0415

        from moat.lib.diffiehellman import DiffieHellman  # noqa: PLC0415

        dh = DiffieHellman()
        dh.generate_private_key()
        dh.generate_public_key()

        pwd_hash = _hash_password(password)
        # Phase 1: send our public key; server responds with theirs + challenge
        res = await self.remote(str(dh.public_key))
        if res is None:
            return
        server_pubkey = int(res[0])
        enc_challenge = bytes(res[1])

        shared_key = dh.generate_shared_secret(server_pubkey)
        key = sha256(shared_key.encode()).digest()

        box = nacl.secret.SecretBox(key)
        challenge = box.decrypt(enc_challenge)
        enc_pwd = box.encrypt(pwd_hash)
        # Phase 2: send username + encrypted password + challenge response
        await self.remote(user, enc_pwd, challenge)

    async def cmd(self, *args: object) -> tuple | None:
        """Server-side: handle incoming credential submission.

        Without DH: ``(username, password_hash)``.
        With DH: ``(public_key,)`` then ``(username, enc_pwd, challenge_resp)``.
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

        First call: ``(client_public_key,)`` → returns
        ``(server_public_key, encrypted_challenge)``.

        Second call: ``(username, encrypted_password, challenge_response)``
        → validates and accepts/denies.
        """
        from ssl import RAND_bytes  # noqa: PLC0415

        import nacl.secret  # noqa: PLC0415

        from moat.lib.diffiehellman import DiffieHellman  # noqa: PLC0415

        if len(args) == 1:
            # Phase 1: receive client's public key, send ours + a challenge
            client_pubkey = int(args[0])

            dh = DiffieHellman()
            dh.generate_private_key()
            dh.generate_public_key()

            shared_key = dh.generate_shared_secret(client_pubkey)
            key = sha256(shared_key.encode()).digest()

            challenge = RAND_bytes(16)
            box = nacl.secret.SecretBox(key)
            enc_challenge = box.encrypt(challenge)
            # Store state for phase 2
            self._dh_key = key
            self._dh_challenge = challenge

            return (str(dh.public_key), enc_challenge)

        # Phase 2: receive username + encrypted password + challenge response
        try:
            if len(args) < 3:
                raise AuthFailed("Incomplete DH phase-2 payload")

            user = args[0]
            enc_pwd = _to_bytes(args[1])
            challenge_resp = _to_bytes(args[2])

            key = getattr(self, "_dh_key", None)
            if key is None:
                raise AuthFailed("DH phase 1 not received")

            if challenge_resp is None:
                raise AuthFailed("Invalid challenge response type")

            challenge = getattr(self, "_dh_challenge", b"")
            if not hmac.compare_digest(challenge_resp, challenge):
                raise AuthFailed("Challenge mismatch")

            if enc_pwd is None:
                raise AuthFailed("Invalid encrypted password type")

            box = nacl.secret.SecretBox(key)
            try:
                pwd_hash = box.decrypt(enc_pwd)
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

        self._done_evt.set()
        return None
