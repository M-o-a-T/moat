"""
Tests for username/password auth.
"""

from __future__ import annotations

import pytest
from contextlib import suppress
from hashlib import sha256

import nacl.secret

from moat.util import attrdict, yload
from moat.lib.diffiehellman import DiffieHellman
from moat.lib.micro import Event
from moat.lib.path import P
from moat.lib.rpc._test import rpc_stack
from moat.lib.rpc.auth import password as auth_password
from moat.lib.rpc.auth._base import AuthDenied
from moat.lib.rpc.auth.password import _to_bytes

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


def _dh_setup(is_server: bool, auth, fail_invalid: bool = False):
    """Create a SubAuth with DH enabled and a client DH keypair."""
    sub, parent, _remote = _password_subauth(
        is_server=is_server, auth=auth, dh=True, fail_invalid=fail_invalid
    )
    client_dh = DiffieHellman()
    client_dh.generate_private_key()
    client_dh.generate_public_key()
    return sub, parent, client_dh


async def test_password_dh_server_phase1_returns_pubkey_and_challenge():
    """DH server phase 1 returns its public key and an encrypted challenge."""
    sub, parent, client_dh = _dh_setup(True, {"alice": "sekrit"})

    res = await sub.cmd(str(client_dh.public_key))
    assert res is not None
    server_pubkey_str, enc_challenge = res
    assert isinstance(server_pubkey_str, str)
    assert isinstance(enc_challenge, bytes)
    # Server should not have accepted or denied yet
    assert parent.accepted == []
    assert parent.denied == []


async def test_password_dh_full_exchange_accepts_correct_password():
    """Full DH exchange with correct password is accepted."""
    sub, parent, client_dh = _dh_setup(True, {"alice": "sekrit"})

    # Phase 1: client → server
    res = await sub.cmd(str(client_dh.public_key))
    assert res is not None
    server_pubkey_str, enc_challenge = res
    server_pubkey = int(server_pubkey_str)

    # Client computes shared key
    shared_key = client_dh.generate_shared_secret(server_pubkey)
    key = sha256(shared_key.encode()).digest()
    box = nacl.secret.SecretBox(key)

    # Decrypt challenge
    challenge = box.decrypt(enc_challenge)

    # Encrypt password hash
    pwd_hash = sha256(b"sekrit").digest()
    enc_pwd = box.encrypt(pwd_hash)

    # Phase 2: client → server
    await sub.cmd("alice", enc_pwd, challenge)
    assert parent.accepted == ["pwd"]
    assert parent.denied == []


async def test_password_dh_full_exchange_denies_wrong_password():
    """Full DH exchange with wrong password is denied when fail_invalid is set."""
    sub, parent, client_dh = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)

    res = await sub.cmd(str(client_dh.public_key))
    assert res is not None
    server_pubkey_str, enc_challenge = res
    shared_key = client_dh.generate_shared_secret(int(server_pubkey_str))
    key = sha256(shared_key.encode()).digest()
    box = nacl.secret.SecretBox(key)
    challenge = box.decrypt(enc_challenge)

    # Wrong password
    pwd_hash = sha256(b"wrong").digest()
    enc_pwd = box.encrypt(pwd_hash)

    await sub.cmd("alice", enc_pwd, challenge)
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_denies_bad_challenge_response():
    """DH server denies when the challenge response doesn't match."""
    sub, parent, client_dh = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)

    res = await sub.cmd(str(client_dh.public_key))
    assert res is not None
    server_pubkey_str, _enc_challenge = res
    shared_key = client_dh.generate_shared_secret(int(server_pubkey_str))
    key = sha256(shared_key.encode()).digest()
    box = nacl.secret.SecretBox(key)

    pwd_hash = sha256(b"sekrit").digest()
    enc_pwd = box.encrypt(pwd_hash)

    # Send wrong challenge response
    await sub.cmd("alice", enc_pwd, b"bad_challenge")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]


async def test_password_dh_denies_phase2_without_phase1():
    """DH server denies phase 2 when phase 1 was never received."""
    sub, parent, _client_dh = _dh_setup(True, {"alice": "sekrit"}, fail_invalid=True)

    pwd_hash = sha256(b"sekrit").digest()
    enc_pwd = nacl.secret.SecretBox(b"\x00" * 32).encrypt(pwd_hash)

    await sub.cmd("alice", enc_pwd, b"challenge")
    assert parent.accepted == []
    assert parent.denied == ["pwd"]
