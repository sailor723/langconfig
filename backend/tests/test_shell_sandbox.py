"""The shell sandbox: what it builds, and what it says when it cannot run.

What can be tested without the OS cooperating: the profile/argument generation, the
wrap/fallback decision, and the honest reporting. What cannot be tested here is the
sandbox actually denying a read — this development machine refuses `sandbox_apply`
itself, so a test asserting enforcement would only prove the harness works.
"""

import sys

from tools import shell_sandbox as sb


def test_macos_profile_hides_the_other_accounts_and_allows_only_ours(tmp_path):
    own = tmp_path / "users" / "284"
    install = tmp_path
    profile = sb._macos_profile(own, install)

    assert "(deny default)" in profile
    # Every account tree denied first…
    assert f'(deny file-read* (subpath "{install / "users"}"' in profile
    # …then the caller's own handed back, after the deny (SBPL: last match wins).
    assert profile.index(f'(deny file-read* (subpath "{install / "users"}"') \
        < profile.index(f'(allow file-read* (subpath "{own}"))')
    # Writes are denied everywhere except one's own tree and temp space.
    assert "(deny file-write*)" in profile
    assert f'(allow file-write* (subpath "{own}"))' in profile
    assert any(tmp in profile for tmp in sb._TEMP_DIRS)


def test_linux_bwrap_hides_the_users_dir_and_binds_ours_back(tmp_path):
    own = tmp_path / "users" / "284"
    args = sb._linux_bwrap_args(own, tmp_path)
    joined = " ".join(args)

    assert f"--tmpfs {tmp_path / 'users'}" in joined
    assert f"--bind {own} {own}" in joined
    assert "--chdir" in joined
    # The tmpfs must come before the bind, or the bind is hidden by it.
    assert joined.index("--tmpfs") < joined.index("--bind")


def test_wrap_returns_none_when_no_mechanism_is_available(monkeypatch):
    """Falling back is the honest answer; pretending would be the dangerous one."""
    monkeypatch.setitem(sb._probe_cache if sb._probe_cache else {}, "x", None)
    sb.reset_probe()
    monkeypatch.setattr(sb, "available", lambda: {"kind": None, "reason": "no sandbox"})
    assert sb.wrap("cat /etc/passwd", "/tmp/ws/users/1", "/tmp/ws") is None


def test_wrap_builds_a_command_for_each_mechanism(tmp_path, monkeypatch):
    own = tmp_path / "users" / "1"
    monkeypatch.setattr(sb, "available", lambda: {"kind": "macos", "reason": "test"})
    wrapped = sb.wrap("rm -rf /", own, tmp_path)
    assert wrapped.startswith("/usr/bin/sandbox-exec -p ")
    assert "/bin/bash -c" in wrapped and "rm -rf /" in wrapped

    monkeypatch.setattr(sb, "available", lambda: {"kind": "bwrap", "reason": "test"})
    wrapped = sb.wrap("rm -rf /", own, tmp_path)
    assert wrapped.startswith("bwrap ")
    assert "--tmpfs" in wrapped


def test_describe_never_claims_enforcement_it_does_not_have():
    """Whatever the verdict, the string says which mechanism or 'none'."""
    text = sb.describe()
    assert text.startswith(("macos", "bwrap", "none"))


def test_the_probe_is_cached(monkeypatch):
    sb.reset_probe()
    calls = {"n": 0}
    real_run = sb.subprocess.run

    def counting(*a, **kw):
        calls["n"] += 1
        return real_run(*a, **kw)

    monkeypatch.setattr(sb.subprocess, "run", counting)
    sb.available()
    first = calls["n"]
    sb.available()
    assert calls["n"] == first, "the probe must not run on every tool call"
    sb.reset_probe()
