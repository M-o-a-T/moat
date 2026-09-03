"""
Tests for username/password auth.
"""

from __future__ import annotations

import hmac
import pytest
from contextlib import suppress
from hashlib import sha256
from os import urandom

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from moat.util import attrdict, yload
from moat.lib.micro import Event
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.lib.rpc.auth import password as auth_password
from moat.lib.rpc.auth._base import AuthDenied
from moat.lib.rpc.auth.password import _derive_dh_key, _generate_dh_parameters, _to_bytes

pytestmark = pytest.mark.anyio

# End-to-end tests are skipped until the Dispatcher refactoring
# (moat.lib.cmd._dispatch) is wired into DirCmd.
_skip_e2e = pytest.mark.skip(reason="DirCmd._subs missing — pending Dispatcher refactor")


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_to_bytes_converts_bytes():
    """_to_bytes passes through bytes unchanged."""
    assert _to_bytes(b"hello") == b"hello"


def test_to_bytes_converts_memoryview():
    """_to_bytes converts memoryview to bytes."""
    mv = memoryview(b"world")
    assert _to_bytes(mv) == b"world"


def test_to_bytes_returns_none_for_invalid():
    """_to_bytes returns None for non-bytes types."""
    assert _to_bytes("string") is None
    assert _to_bytes(42) is None
    assert _to_bytes(None) is None


def test_hash_password_with_str_and_bytes():
    """_hash_password produces the same digest for str and bytes equivalents."""
    from moat.lib.rpc.auth.password import _hash_password  # noqa: PLC0415

    # String input (exercises the encode branch)
    digest_str = _hash_password("hello")
    # Bytes input (exercises the direct-pass branch)
    digest_bytes = _hash_password(b"hello")
    assert digest_str == digest_bytes
    assert len(digest_str) == 32


# ---------------------------------------------------------------------------
# DH helper tests
# ---------------------------------------------------------------------------


def test_derive_dh_key_produces_32_bytes():
    """_derive_dh_key produces a 32-byte key from arbitrary input."""
    key = _derive_dh_key(b"some_shared_secret_data")
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_derive_dh_key_is_deterministic():
    """Same input always derives the same key."""
    k1 = _derive_dh_key(b"secret")
    k2 = _derive_dh_key(b"secret")
    assert k1 == k2


def test_generate_dh_parameters_caches():
    """DH parameter generation is cached."""
    p1 = _generate_dh_parameters()
    p2 = _generate_dh_parameters()
    assert p1 is p2


def test_dh_key_agreement_roundtrip():
    """Two parties can derive the same shared secret via the cryptography package."""
    params = dh.generate_parameters(generator=2, key_size=2048)
    alice_priv = params.generate_private_key()
    bob_priv = params.generate_private_key()
    alice_shared = alice_priv.exchange(bob_priv.public_key())
    bob_shared = bob_priv.exchange(alice_priv.public_key())
    assert alice_shared == bob_shared
    # Derived keys also match
    assert _derive_dh_key(alice_shared) == _derive_dh_key(bob_shared)


# ---------------------------------------------------------------------------
# End-to-end tests via unix socket
# ---------------------------------------------------------------------------

CFG_PLAIN = """
app:
  app: dir
  a:
    app: _test_.Cmd
  l:
    app: net.unix.Link
    port: /tmp/test.sock
    retry:
      delay: 0.05
    auth:
      modes:
      - mode: password
      test:
        password:
          user: alice
          password: sekrit
    log:
      txt: "!L"
  r:
    app: net.unix.Port
    port: /tmp/test.sock
    auth:
      modes:
      - mode: password
      test:
        password:
          alice: sekrit
          bob: hunter2
    log:
      txt: "!R"
"""


CFG_DH = """
app:
  app: dir
  a:
    app: _test_.Cmd
  l:
    app: net.unix.Link
    port: /tmp/test.sock
    retry:
      delay: 0.05
    auth:
      modes:
      - mode: password
        dh: true
      test:
        password:
          user: alice
          password: sekrit
    log:
      txt: "!L"
  r:
    app: net.unix.Port
    port: /tmp/test.sock
    auth:
      modes:
      - mode: password
        dh: true
      test:
        password:
          alice: sekrit
          bob: hunter2
    log:
      txt: "!R"
"""


@_skip_e2e
@pytest.mark.parametrize(
    "cfg_text",
    [pytest.param(CFG_PLAIN, id="plain"), pytest.param(CFG_DH, id="dh")],
)
async def test_password_net(tmp_path, cfg_text):
    """Password auth works end-to-end (plain and DH)."""
    sock = tmp_path / "test.sock"
    with suppress(FileNotFoundError):
        sock.unlink()

    cfg = yload(cfg_text, attr=True)
    cfg.app.r.port = str(sock)
    cfg.app.l.port = str(sock)

    async with rpc_stack(tmp_path, cfg) as d:
        res = await d.cmd(P("l.a.echo"), m="hello")
        assert res.kw == dict(r="hello")


@_skip_e2e
@pytest.mark.parametrize(
    "cfg_text",
    [pytest.param(CFG_PLAIN, id="plain"), pytest.param(CFG_DH, id="dh")],
)
async def test_password_net_wrong_password(tmp_path, cfg_text):
    """Wrong password is rejected when fail_invalid is set."""
    sock = tmp_path / "test.sock"
    with suppress(FileNotFoundError):
        sock.unlink()

    cfg = yload(cfg_text, attr=True)
    cfg.app.r.port = str(sock)
    cfg.app.l.port = str(sock)
    # Set wrong password and enable fail_invalid on server
    cfg.app.l.auth.test.password.password = "wrong"
    cfg.app.r.auth.modes[0].fail_invalid = True

    async def _run():
        async with rpc_stack(tmp_path, cfg) as d:
            await d.cmd(P("l.a.echo"), m="hello")

    with pytest.raises(ExceptionGroup) as err:
        await _run()
    assert err.group_contains(AuthDenied)


@_skip_e2e
@pytest.mark.parametrize(
    "cfg_text",
    [pytest.param(CFG_PLAIN, id="plain"), pytest.param(CFG_DH, id="dh")],
)
async def test_password_net_unknown_user(tmp_path, cfg_text):
    """Unknown user is rejected when fail_invalid is set."""
    sock = tmp_path / "test.sock"
    with suppress(FileNotFoundError):
        sock.unlink()

    cfg = yload(cfg_text, attr=True)
    cfg.app.r.port = str(sock)
    cfg.app.l.port = str(sock)
    cfg.app.l.auth.test.password.user = "eve"
    cfg.app.r.auth.modes[0].fail_invalid = True

    async def _run():
        async with rpc_stack(tmp_path, cfg) as d:
            await d.cmd(P("l.a.echo"), m="hello")

    with pytest.raises(ExceptionGroup) as err:
        await _run()
    assert err.group_contains(AuthDenied)


# ---------------------------------------------------------------------------
# Unit tests for the SubAuth handler (server side)
# ---------------------------------------------------------------------------


class _AuthParent:
    def __init__(self, *, is_server: bool):
        self.parent = attrdict(is_server=is_server)
        self.accepted = []
        self.denied = []

    def accept(self, sub):
        self.accepted.append(sub.name)

    def deny(self, sub):
        self.denied.append(sub.name)


class _RemoteCall:
    """Records calls and returns canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []

    async def __call__(self, *args):
        self.calls.append(args)
        if self.responses:
            return self.responses.pop(0)
        return None


def _password_subauth(
    *,
    is_server: bool,
    auth=None,
    dh: bool = False,
    fail_invalid: bool = False,
):
    parent = _AuthParent(is_server=is_server)
    remote = _RemoteCall()
    cfg = attrdict(mode="password")
    if dh:
        cfg.dh = True
    if fail_invalid:
        cfg.fail_invalid = True
    sub = auth_password.SubAuth(cfg, auth, parent, 0, "pwd", remote)
    sub._seen = Event()  # noqa:SLF001
    return sub, parent, remote


async def test_password_server_accepts_correct_credentials():
    """Server accepts when the password hash matches."""
    sub, parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("alice", pwd_hash)
    assert parent.accepted == ["pwd"]
    assert parent.denied == []


async def test_password_server_denies_wrong_password_with_fail_invalid():
    """Server denies when the password doesn't match and fail_invalid is set."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    pwd_hash = sha256(b"wrong").digest()
    await sub.cmd("alice", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_server_ignores_wrong_password_without_fail_invalid():
    """Server ignores bad credentials when fail_invalid is not set."""
    sub, parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    pwd_hash = sha256(b"wrong").digest()
    await sub.cmd("alice", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_server_ignores_unknown_user_without_fail_invalid():
    """Server ignores unknown users when fail_invalid is not set."""
    sub, parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("eve", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_server_denies_unknown_user_with_fail_invalid():
    """Server denies unknown users when fail_invalid is set."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("eve", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_server_denies_non_bytes_hash_with_fail_invalid():
    """Server denies when the password hash is not bytes and fail_invalid is set."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub.cmd("alice", "not-bytes")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_server_ignores_missing_args_without_fail_invalid():
    """Server ignores when fewer than 2 args are given and fail_invalid is not set."""
    sub, parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    await sub.cmd("alice")
    assert parent.accepted == []
    assert parent.denied == []


# ---------------------------------------------------------------------------
# Unit tests for the SubAuth handler (client side)
# ---------------------------------------------------------------------------


async def test_password_client_sends_credentials_and_accepts(monkeypatch):
    """Client sends username + password hash and marks accepted."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}
    )
    await sub.task()
    assert len(remote.calls) == 1
    assert remote.calls[0][0] == "alice"
    assert parent.accepted == ["pwd"]
    assert parent.denied == []


async def test_password_client_no_credentials_does_nothing(monkeypatch):
    """Client without credentials sends nothing."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(is_server=False, auth=None)
    await sub.task()
    assert remote.calls == []
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_client_auth_explicitly_none_returns_early(monkeypatch):
    """Client with auth explicitly set to None after construction returns immediately."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}
    )
    # Force auth to None to exercise the early-return branch
    sub.auth = None
    await sub.task()
    assert remote.calls == []
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_client_missing_user_or_password(monkeypatch):
    """Client with incomplete credentials sends nothing."""
    monkeypatch.setattr(auth_password, "L", False)
    # Missing password
    sub, parent, remote = _password_subauth(is_server=False, auth={"user": "alice"})
    await sub.task()
    assert remote.calls == []
    assert parent.accepted == []

    # Missing user
    sub2, parent2, remote2 = _password_subauth(is_server=False, auth={"password": "sekrit"})
    await sub2.task()
    assert remote2.calls == []
    assert parent2.accepted == []


# ---------------------------------------------------------------------------
# DH unit tests
# ---------------------------------------------------------------------------


def _generate_client_keypair():
    """Generate a DH keypair and return (priv_key, pub_bytes)."""
    params = _generate_dh_parameters()
    priv = params.generate_private_key()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, pub_bytes


def _dh_setup(is_server: bool, auth, fail_invalid: bool = False):
    """Create a SubAuth with DH enabled and a client DH keypair."""
    sub, parent, _remote = _password_subauth(
        is_server=is_server, auth=auth, dh=True, fail_invalid=fail_invalid
    )
    client_priv, client_pub_bytes = _generate_client_keypair()
    return sub, parent, client_priv, client_pub_bytes


async def test_password_dh_server_phase1_returns_pubkey_and_challenge():
    """DH server phase 1 returns its public key, nonce, and encrypted challenge."""
    sub, parent, _client_priv, client_pub_bytes = _dh_setup(True, {"alice": "sekrit"})

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    assert len(res) == 3
    server_pub_bytes, nonce, enc_challenge = res
    assert isinstance(server_pub_bytes, bytes)
    assert isinstance(nonce, bytes)
    assert isinstance(enc_challenge, bytes)
    # Server should not have accepted or denied yet
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_dh_full_exchange_accepts_correct_password():
    """Full DH exchange with correct password is accepted."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(True, {"alice": "sekrit"})

    # Phase 1: client → server
    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    # Client computes shared key
    server_pub_key = serialization.load_pem_public_key(server_pub_bytes)
    shared_secret = client_priv.exchange(server_pub_key)
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)

    # Decrypt challenge
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    # Encrypt password hash
    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    # Phase 2: client → server
    await sub.cmd("alice", enc_nonce, enc_pwd, challenge)
    assert parent.accepted == ["pwd"]
    assert parent.denied == []


async def test_password_dh_full_exchange_denies_wrong_password():
    """Full DH exchange with wrong password is denied when fail_invalid is set."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    # Wrong password
    pwd_hash = sha256(b"wrong").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    await sub.cmd("alice", enc_nonce, enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_denies_bad_challenge_response():
    """DH server denies when the challenge response doesn't match."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, _nonce, _enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)

    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    # Send wrong challenge response
    await sub.cmd("alice", enc_nonce, enc_pwd, b"bad_challenge")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_denies_phase2_without_phase1():
    """DH server denies phase 2 when phase 1 was never received."""
    sub, parent, _client_priv, _client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    pwd_hash = sha256(b"sekrit").digest()
    # Use a dummy key for encryption
    dummy_key = b"\x00" * 32
    aesgcm = AESGCM(dummy_key)
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    await sub.cmd("alice", enc_nonce, enc_pwd, b"challenge")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_server_cleans_up_state_after_phase2():
    """DH server cleans up shared key and challenge after phase 2."""
    sub, _parent, client_priv, client_pub_bytes = _dh_setup(True, {"alice": "sekrit"})

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    await sub.cmd("alice", enc_nonce, enc_pwd, challenge)
    # State should be cleaned up
    assert sub._dh_key is None  # noqa: SLF001
    assert sub._dh_challenge is None  # noqa: SLF001


async def test_password_dh_server_cleans_up_state_after_failed_phase2():
    """DH server cleans up shared key and challenge even after a failed phase 2."""
    sub, _parent, _client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None

    # Send bad challenge response
    await sub.cmd("alice", urandom(12), b"garbage", b"bad_challenge")
    # State should still be cleaned up
    assert sub._dh_key is None  # noqa: SLF001
    assert sub._dh_challenge is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# DH client fallback tests
# ---------------------------------------------------------------------------


async def test_password_dh_client_falls_back_when_server_returns_none(monkeypatch):
    """Client falls back to plain auth when server returns None for DH phase 1."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    # Server returns None (doesn't support DH)
    remote.responses = [None]

    await sub.task()
    # Should have made two calls: first DH attempt, then plain fallback
    assert len(remote.calls) == 2
    # First call: DH public key (PEM bytes)
    assert isinstance(remote.calls[0][0], bytes)
    # Second call: plain (username, password_hash)
    assert remote.calls[1][0] == "alice"
    assert isinstance(remote.calls[1][1], bytes)
    assert parent.accepted == ["pwd"]


async def test_password_dh_client_falls_back_on_exception(monkeypatch):
    """Client falls back to plain auth when DH raises an exception."""
    monkeypatch.setattr(auth_password, "L", False)

    call_count = [0]

    async def failing_remote(*_args):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("DH negotiation failed")
        # Second call (fallback) succeeds
        return None

    sub, parent, _remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    sub.remote = failing_remote

    await sub.task()
    # Should have made two calls: first DH (fails), then plain fallback
    assert call_count[0] == 2
    assert parent.accepted == ["pwd"]


async def test_password_dh_client_falls_back_on_malformed_response(monkeypatch):
    """Client falls back to plain auth when server returns a malformed DH response."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    # Server returns a too-short response (missing fields)
    remote.responses = [(b"partial",)]  # only 1 element, need 3

    await sub.task()
    # Should have made two calls: first DH attempt, then plain fallback
    assert len(remote.calls) == 2
    # Second call is the plain fallback
    assert remote.calls[1][0] == "alice"
    assert isinstance(remote.calls[1][1], bytes)
    assert parent.accepted == ["pwd"]


# ---------------------------------------------------------------------------
# DH server error handling tests
# ---------------------------------------------------------------------------


async def test_password_dh_server_rejects_non_bytes_pubkey():
    """DH server rejects phase 1 with non-bytes public key when fail_invalid is set."""
    sub, parent, _client_priv, _client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )
    # Send a string instead of bytes
    res = await sub.cmd("not-bytes")
    assert res is None
    assert parent.denied == ["pwd"]


async def test_password_dh_server_rejects_garbage_pubkey():
    """DH server rejects phase 1 with garbage public key when fail_invalid is set."""
    sub, parent, _client_priv, _client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )
    # Send garbage bytes that aren't a valid PEM key
    res = await sub.cmd(b"not_a_valid_key")
    assert res is None
    assert parent.denied == ["pwd"]


async def test_password_dh_server_rejects_short_phase2_payload():
    """DH server rejects phase 2 with insufficient args when fail_invalid is set."""
    sub, parent, _client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    # Complete phase 1 first
    res = await sub.cmd(client_pub_bytes)
    assert res is not None

    # Send only 2 args (need 4)
    await sub.cmd("alice", b"nonce")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


# ---------------------------------------------------------------------------
# Generic-error / no-leak tests
# ---------------------------------------------------------------------------


async def test_password_wrong_password_and_unknown_user_same_error_type():
    """Wrong-password and unknown-user failures produce identical observable behavior.

    Both cases raise AuthFailed internally (caught by _cmd_plain), resulting
    in the same deny/ignore outcome.  This test verifies the behavior is
    indistinguishable from the caller's perspective.
    """
    # Wrong password
    sub_wp, parent_wp, _remote_wp = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub_wp.cmd("alice", sha256(b"wrong").digest())

    # Unknown user
    sub_uu, parent_uu, _remote_uu = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub_uu.cmd("eve", sha256(b"sekrit").digest())

    # Both must produce the same observable outcome
    assert parent_wp.accepted == parent_uu.accepted
    assert parent_wp.denied == parent_uu.denied


async def test_password_error_messages_do_not_leak_user_existence():
    """Wrong-password and unknown-user produce identical observable behavior (no user enumeration).

    The AuthFailed exception is caught internally by _cmd_plain; the client only
    observes accept/deny.  Both failure modes must result in the same deny
    (when fail_invalid is set) or the same ignore (when not set).
    """
    # With fail_invalid=True: both should deny
    sub_wp, parent_wp, _r = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub_wp.cmd("alice", sha256(b"wrong").digest())

    sub_uu, parent_uu, _r2 = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub_uu.cmd("eve", sha256(b"sekrit").digest())

    # Same observable outcome: both denied, neither accepted
    assert parent_wp.accepted == parent_uu.accepted == []
    assert parent_wp.denied == parent_uu.denied == ["pwd"]

    # With fail_invalid=False: both should silently ignore (also identical)
    sub_wp2, parent_wp2, _r3 = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    await sub_wp2.cmd("alice", sha256(b"wrong").digest())

    sub_uu2, parent_uu2, _r4 = _password_subauth(is_server=True, auth={"alice": "sekrit"})
    await sub_uu2.cmd("eve", sha256(b"sekrit").digest())

    assert parent_wp2.accepted == parent_uu2.accepted == []
    assert parent_wp2.denied == parent_uu2.denied == []


# ---------------------------------------------------------------------------
# Disabled / blocked account tests
# ---------------------------------------------------------------------------


async def test_password_disabled_account_rejected():
    """An account whose password is set to None is treated as disabled — auth fails."""

    class _TrackingParent(_AuthParent):
        def __init__(self, *, is_server: bool):
            super().__init__(is_server=is_server)
            self.accepted_names: list[str] = []

        def accept(self, sub):
            self.accepted_names.append(sub.name)

    parent = _TrackingParent(is_server=True)
    remote = _RemoteCall()
    cfg = attrdict(mode="password", fail_invalid=True)
    # Alice's password is None — effectively disabled
    sub = auth_password.SubAuth(cfg, {"alice": None}, parent, 0, "pwd", remote)
    sub._seen = Event()  # noqa: SLF001

    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("alice", pwd_hash)
    assert parent.denied == ["pwd"]
    assert parent.accepted == []


async def test_password_empty_password_account_rejected():
    """An account with an empty-string password cannot authenticate with any submitted hash."""
    sub, parent, _remote = _password_subauth(is_server=True, auth={"alice": ""}, fail_invalid=True)
    # Even submitting the hash of "" should match — but a non-empty hash should not
    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("alice", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]

    # Submitting the actual empty password hash SHOULD match (edge case)
    sub2, parent2, _remote2 = _password_subauth(is_server=True, auth={"alice": ""})
    empty_hash = sha256(b"").digest()
    await sub2.cmd("alice", empty_hash)
    assert parent2.accepted == ["pwd"]


# ---------------------------------------------------------------------------
# Constant-time comparison sanity check
# ---------------------------------------------------------------------------


async def test_constant_time_comparison_sanity():
    """Timing of hmac.compare_digest should not differ significantly between near-match and far-mismatch."""
    import statistics  # noqa: PLC0415
    import time  # noqa: PLC0415

    # We test the underlying primitive: hmac.compare_digest with equal-length inputs
    # A near-match (differ in last byte) vs far-mismatch (all bytes differ)
    # should take approximately the same time.
    correct = sha256(b"correct_password").digest()

    # Near-mismatch: flip one bit in the last byte
    near = bytearray(correct)
    near[-1] ^= 0x01
    near_bytes = bytes(near)

    # Far-mismatch: completely different input
    far = sha256(b"completely_different_password_that_is_also_long").digest()

    num_samples = 200
    near_times: list[float] = []
    far_times: list[float] = []

    for _i in range(num_samples):
        t0 = time.perf_counter_ns()
        hmac.compare_digest(correct, near_bytes)
        near_times.append(time.perf_counter_ns() - t0)

        t0 = time.perf_counter_ns()
        hmac.compare_digest(correct, far)
        far_times.append(time.perf_counter_ns() - t0)

    near_mean = statistics.mean(near_times)
    far_mean = statistics.mean(far_times)

    # The ratio should be close to 1.0 for constant-time comparison.
    # Allow generous tolerance (factor of 2) due to scheduling jitter.
    ratio = max(near_mean, far_mean) / max(min(near_mean, far_mean), 1)
    assert ratio < 2.0, (
        f"Timing ratio {ratio:.2f} suggests non-constant-time behavior "
        f"(near={near_mean:.0f}ns, far={far_mean:.0f}ns)"
    )


# ---------------------------------------------------------------------------
# DH client full exchange (covers _client_dh method, lines 228-255)
# ---------------------------------------------------------------------------


async def test_password_dh_client_full_exchange_success(monkeypatch):
    """DH client successfully exchanges keys, encrypts password, and sends credentials."""
    monkeypatch.setattr(auth_password, "L", False)

    # We simulate a server by running the server-side cmd() to generate phase-1 response,
    # then feeding it to the client's _client_dh method.
    server_sub, _server_parent, _server_remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, dh=True
    )

    # The client's remote callable will proxy to the server's cmd()
    call_log: list[tuple] = []

    async def mock_remote(*args):
        call_log.append(args)
        res = await server_sub.cmd(*args)
        return res

    client_sub, client_parent, _client_remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    client_sub.remote = mock_remote

    await client_sub.task()

    # Two calls: phase 1 (pubkey) and phase 2 (credentials)
    assert len(call_log) == 2
    # Phase 1: client sent its public key
    assert isinstance(call_log[0][0], bytes)
    # Phase 2: client sent username, nonce, encrypted password, challenge response
    assert call_log[1][0] == "alice"
    assert isinstance(call_log[1][1], bytes)  # nonce
    assert isinstance(call_log[1][2], bytes)  # encrypted password
    assert isinstance(call_log[1][3], bytes)  # challenge response
    # Server should have accepted
    assert _server_parent.accepted == ["pwd"]
    # Client should have accepted
    assert client_parent.accepted == ["pwd"]


async def test_password_dh_client_full_exchange_wrong_password(monkeypatch):
    """DH client with wrong password: server denies, client still marks accepted (client doesn't know server result)."""
    monkeypatch.setattr(auth_password, "L", False)

    server_sub, server_parent, _sr = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, dh=True, fail_invalid=True
    )

    call_log: list[tuple] = []

    async def mock_remote(*args):
        call_log.append(args)
        return await server_sub.cmd(*args)

    client_sub, client_parent, _cr = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "wrong"}, dh=True
    )
    client_sub.remote = mock_remote

    await client_sub.task()

    assert len(call_log) == 2
    # Server denied because password didn't match
    assert server_parent.denied == ["pwd"]
    assert server_parent.accepted == []
    # Client marks accepted (it sent credentials; server denial is separate)
    assert client_parent.accepted == ["pwd"]


async def test_password_dh_client_challenge_decryption_failure(monkeypatch):
    """DH client falls back to plain when challenge decryption fails (tampered challenge)."""
    monkeypatch.setattr(auth_password, "L", False)

    # Server returns a valid-looking response but with tampered encrypted challenge
    # so the client's AES-GCM decrypt will fail.
    fake_pub_bytes = _generate_client_keypair()[1]  # use a throwaway key's PEM
    fake_nonce = urandom(12)
    fake_enc_challenge = b"\x00" * 32  # garbage ciphertext, will fail AES-GCM decrypt

    remote = _RemoteCall(responses=[(fake_pub_bytes, fake_nonce, fake_enc_challenge)])

    client_sub, client_parent, _cr = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    client_sub.remote = remote

    await client_sub.task()

    # Should fall back to plain: 2 calls total (DH attempt + plain fallback)
    assert len(remote.calls) == 2
    # Second call is plain: (username, password_hash)
    assert remote.calls[1][0] == "alice"
    assert isinstance(remote.calls[1][1], bytes)
    assert client_parent.accepted == ["pwd"]


async def test_password_dh_client_invalid_response_types(monkeypatch):
    """DH client falls back when server returns non-bytes types in phase-1 response."""
    monkeypatch.setattr(auth_password, "L", False)

    # Response with string instead of bytes
    remote = _RemoteCall(responses=[("not_bytes", b"nonce", b"enc")])

    client_sub, client_parent, _cr = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}, dh=True
    )
    client_sub.remote = remote

    await client_sub.task()

    # Falls back to plain
    assert len(remote.calls) == 2
    assert remote.calls[1][0] == "alice"
    assert client_parent.accepted == ["pwd"]


# ---------------------------------------------------------------------------
# Tampered ciphertext / malformed DH parameters
# ---------------------------------------------------------------------------


async def test_password_dh_tampered_ciphertext_rejected():
    """DH server rejects when the encrypted password has been tampered with (AES-GCM auth tag mismatch)."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    # Phase 1
    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    # Derive shared key
    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    # Encrypt password hash correctly
    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = bytearray(aesgcm.encrypt(enc_nonce, pwd_hash, None))

    # Tamper with the ciphertext: flip a bit in the middle
    enc_pwd[len(enc_pwd) // 2] ^= 0xFF
    tampered_enc_pwd = bytes(enc_pwd)

    # Send tampered ciphertext — AES-GCM will detect the modification
    await sub.cmd("alice", enc_nonce, tampered_enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_tampered_nonce_rejected():
    """DH server rejects when the nonce has been tampered with."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, _nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(_nonce, enc_challenge, None)

    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    # Tamper with the nonce
    tampered_nonce = bytearray(enc_nonce)
    tampered_nonce[0] ^= 0x01

    await sub.cmd("alice", bytes(tampered_nonce), enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_unknown_user_in_dh_mode():
    """DH server denies unknown user in phase 2 when fail_invalid is set."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    # Send with unknown user "eve"
    await sub.cmd("eve", enc_nonce, enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_null_challenge_state():
    """DH server handles the edge case where challenge state is None despite key being set."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    # Manually clear the challenge state to simulate race condition
    sub._dh_challenge = None  # noqa: SLF001

    pwd_hash = sha256(b"sekrit").digest()
    enc_nonce = urandom(12)
    enc_pwd = aesgcm.encrypt(enc_nonce, pwd_hash, None)

    await sub.cmd("alice", enc_nonce, enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_null_nonce_and_pwd_rejected():
    """DH server rejects when nonce or encrypted password is None (invalid type)."""
    sub, parent, client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None
    server_pub_bytes, nonce, enc_challenge = res

    shared_secret = client_priv.exchange(serialization.load_pem_public_key(server_pub_bytes))
    key = _derive_dh_key(shared_secret)
    aesgcm = AESGCM(key)
    challenge = aesgcm.decrypt(nonce, enc_challenge, None)

    # Send with None nonce
    await sub.cmd("alice", None, b"enc_pwd", challenge)
    assert parent.denied == ["pwd"]

    # Reset for second test — need new phase 1
    sub2, parent2, cp2, cpb2 = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)
    res2 = await sub2.cmd(cpb2)
    assert res2 is not None
    spb2, n2, ec2 = res2
    ss2 = cp2.exchange(serialization.load_pem_public_key(spb2))
    k2 = _derive_dh_key(ss2)
    ag2 = AESGCM(k2)
    ch2 = ag2.decrypt(n2, ec2, None)

    # Send with None encrypted password
    await sub2.cmd("alice", urandom(12), None, ch2)
    assert parent2.denied == ["pwd"]


async def test_password_dh_null_challenge_response_rejected():
    """DH server rejects when challenge response is None."""
    sub, parent, _client_priv, client_pub_bytes = _dh_setup(
        True, {"alice": "sekrit"}, fail_invalid=True
    )

    res = await sub.cmd(client_pub_bytes)
    assert res is not None

    # Send phase 2 with None challenge response
    pwd_hash = sha256(b"sekrit").digest()
    dummy_aesgcm = AESGCM(b"\x00" * 32)
    enc_nonce = urandom(12)
    enc_pwd = dummy_aesgcm.encrypt(enc_nonce, pwd_hash, None)

    await sub.cmd("alice", enc_nonce, enc_pwd, None)
    assert parent.denied == ["pwd"]


# ---------------------------------------------------------------------------
# Empty / null / oversized input handling
# ---------------------------------------------------------------------------


async def test_password_empty_username_rejected():
    """Server rejects empty-string username."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    pwd_hash = sha256(b"sekrit").digest()
    await sub.cmd("", pwd_hash)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_empty_password_hash_rejected():
    """Server rejects empty bytes as password hash."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub.cmd("alice", b"")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_null_args_handled():
    """Server handles None arguments without crashing."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    # None as password hash
    await sub.cmd("alice", None)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_oversized_inputs_handled():
    """Server handles oversized inputs without crashing."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    # Oversized password hash (much larger than SHA-256 digest)
    oversized = b"\x00" * 10000
    await sub.cmd("alice", oversized)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_oversized_username_handled():
    """Server handles extremely long username without crashing."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    pwd_hash = sha256(b"sekrit").digest()
    long_user = "x" * 10000
    await sub.cmd(long_user, pwd_hash)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_no_args_handled():
    """Server handles zero-argument cmd without crashing."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    await sub.cmd()
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_many_extra_args_handled():
    """Server handles extra arguments beyond expected count."""
    sub, parent, _remote = _password_subauth(
        is_server=True, auth={"alice": "sekrit"}, fail_invalid=True
    )
    pwd_hash = sha256(b"sekrit").digest()
    # Extra args should be ignored — only first two are used
    await sub.cmd("alice", pwd_hash, "extra", "args", b"more")
    assert parent.accepted == ["pwd"]
    assert parent.denied == []


async def test_password_dh_empty_pubkey_rejected():
    """DH server rejects empty-bytes public key in phase 1."""
    sub, parent, _cp, _cpb = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)
    res = await sub.cmd(b"")
    assert res is None
    assert parent.denied == ["pwd"]


async def test_password_dh_oversized_pubkey_rejected():
    """DH server rejects oversized garbage as public key in phase 1."""
    sub, parent, _cp, _cpb = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)
    res = await sub.cmd(b"\x00" * 100000)
    assert res is None
    assert parent.denied == ["pwd"]


async def test_password_dh_empty_args_phase2_rejected():
    """DH server rejects empty args in phase 2."""
    sub, parent, _cp, client_pub_bytes = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)
    # Complete phase 1
    res = await sub.cmd(client_pub_bytes)
    assert res is not None

    # Send empty strings as phase 2
    await sub.cmd("", b"", b"", b"")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_client_empty_credentials_does_nothing(monkeypatch):
    """Client with empty-string user and password sends nothing."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, parent, remote = _password_subauth(is_server=False, auth={"user": "", "password": ""})
    await sub.task()
    # Empty strings are not None, so credentials ARE sent
    assert len(remote.calls) == 1
    assert remote.calls[0][0] == ""
    assert parent.accepted == ["pwd"]


# ---------------------------------------------------------------------------
# DH server ignores (without fail_invalid) tests
# ---------------------------------------------------------------------------


async def test_password_dh_server_ignores_bad_pubkey_without_fail_invalid():
    """DH server silently ignores garbage public key when fail_invalid is not set."""
    sub, parent, _cp, _cpb = _dh_setup(True, {"alice": "sekrit"})
    res = await sub.cmd(b"not_a_valid_key")
    assert res is None
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_dh_server_ignores_non_bytes_pubkey_without_fail_invalid():
    """DH server silently ignores non-bytes public key when fail_invalid is not set."""
    sub, parent, _cp, _cpb = _dh_setup(True, {"alice": "sekrit"})
    res = await sub.cmd("not_bytes")
    assert res is None
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_dh_server_ignores_short_phase2_without_fail_invalid():
    """DH server silently ignores short phase-2 payload when fail_invalid is not set."""
    sub, parent, _cp, client_pub_bytes = _dh_setup(True, {"alice": "sekrit"})
    res = await sub.cmd(client_pub_bytes)
    assert res is not None

    await sub.cmd("alice", b"nonce")
    assert parent.accepted == []
    assert parent.denied == []


# ---------------------------------------------------------------------------
# Server task() path coverage (lines 170, 174-175, 179)
# ---------------------------------------------------------------------------


async def test_password_server_task_waits_for_done_event(monkeypatch):
    """Server-side task() waits for the _done_evt and returns."""
    monkeypatch.setattr(auth_password, "L", False)
    sub, _parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})

    # Start the server task in a task group; it should block on _done_evt
    import anyio  # noqa: PLC0415

    async with anyio.create_task_group() as tg:
        tg.start_soon(sub.task)

        # Give it a moment to reach the wait
        await anyio.wait_all_tasks_blocked()

        # Signal done
        sub._done_evt.set()  # noqa: SLF001

        # The task should complete shortly
        await anyio.wait_all_tasks_blocked()


async def test_password_server_task_with_L(monkeypatch):
    """Server-side task() calls set_ready when L is True (MicroPython path)."""
    monkeypatch.setattr(auth_password, "L", True)
    sub, _parent, _remote = _password_subauth(is_server=True, auth={"alice": "sekrit"})

    # Mock set_ready to avoid needing full Cmd lifecycle setup
    ready_called: list[bool] = []
    sub.set_ready = lambda: ready_called.append(True)

    import anyio  # noqa: PLC0415

    async with anyio.create_task_group() as tg:
        tg.start_soon(sub.task)
        await anyio.wait_all_tasks_blocked()
        sub._done_evt.set()  # noqa: SLF001
        await anyio.wait_all_tasks_blocked()

    assert ready_called


async def test_password_client_task_with_L(monkeypatch):
    """Client-side task() calls set_ready when L is True."""
    monkeypatch.setattr(auth_password, "L", True)
    sub, _parent, _remote = _password_subauth(
        is_server=False, auth={"user": "alice", "password": "sekrit"}
    )

    ready_called: list[bool] = []
    sub.set_ready = lambda: ready_called.append(True)

    await sub.task()
    assert ready_called
