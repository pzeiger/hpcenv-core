"""Tests of github-identity.sh in a temporary HOME with the real git and no real config.

Every case runs bash with HOME pointing into tmp_path, system and inherited git config
switched off, and ok/warn defined to print their message, so nothing touches the real home."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "github-identity.sh"
NOREPLY = "12345+someone@users.noreply.github.com"
FORMS = 8   # one includeIf entry for each way of writing a github.com remote


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def bash(home, body, check=True):
    """Run `body` with github-identity.sh sourced; returns the CompletedProcess."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "XDG_"))}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1")
    prelude = (f'set -euo pipefail\nok() {{ echo "ok: $*"; }}\nwarn() {{ echo "warn: $*"; }}\n'
               f'. "{SCRIPT}"\n')
    result = subprocess.run(["bash", "-c", prelude + body], env=env, capture_output=True,
                            text=True)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def git_email(home, remote):
    """The user.email a commit in a repository with this remote would carry."""
    repo = home / "repo"
    shutil.rmtree(repo, ignore_errors=True)
    subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True,
                   env={"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "PATH": os.environ["PATH"]})
    out = bash(home, f'git -C "{repo}" remote add origin "{remote}"; '
                     f'git -C "{repo}" config --get user.email || true')
    return out.stdout.strip()


@pytest.mark.parametrize("address", [NOREPLY, "a@example.org", "first.last@mail.example.org"])
def test_valid_accepts_an_address(home, address):
    bash(home, f'github_identity_valid "{address}"')


@pytest.mark.parametrize("address", ["", "a@b", "a b@c.d", "a@@b.c", "@b.c", "a@.c", "plain"])
def test_valid_rejects_a_non_address(home, address):
    assert bash(home, f'github_identity_valid "{address}"', check=False).returncode == 1


def test_set_writes_the_file_and_one_entry_per_remote_form(home):
    bash(home, f'github_identity_set "{NOREPLY}"')
    assert (home / ".gitconfig-github").read_text().split() == ["[user]", "email", "=", NOREPLY]
    entries = [line for line in (home / ".gitconfig").read_text().splitlines()
               if line.strip().startswith("path")]
    assert len(entries) == FORMS
    assert all(line.split("=")[1].strip() == "~/.gitconfig-github" for line in entries)


@pytest.mark.parametrize("remote", [
    "https://github.com/o/r", "https://user@github.com/o/r", "git@github.com:o/r.git",
    "github.com:o/r.git", "ssh://git@github.com/o/r.git", "ssh://git@github.com:22/o/r.git",
    "ssh://github.com/o/r.git", "ssh://git@ssh.github.com:443/o/r.git"])
def test_github_remote_commits_with_the_github_address(home, remote):
    (home / ".gitconfig").write_text("[user]\n\temail = personal@example.org\n")
    bash(home, f'github_identity_set "{NOREPLY}"')
    assert git_email(home, remote) == NOREPLY


def test_other_remote_keeps_the_global_address(home):
    (home / ".gitconfig").write_text("[user]\n\temail = personal@example.org\n")
    bash(home, f'github_identity_set "{NOREPLY}"')
    assert git_email(home, "https://gitlab.com/o/r") == "personal@example.org"
    assert git_email(home, "https://github.com.evil.example/o/r") == "personal@example.org"


def test_set_twice_keeps_one_entry_per_form(home):
    bash(home, f'github_identity_set "{NOREPLY}"; github_identity_set "{NOREPLY}"')
    assert (home / ".gitconfig").read_text().count("[includeIf") == FORMS


def test_effective_is_empty_without_any_address(home):
    assert bash(home, "github_identity_effective").stdout == "\n"


def test_effective_is_the_global_address_before_the_rule(home):
    (home / ".gitconfig").write_text("[user]\n\temail = personal@example.org\n")
    assert bash(home, "github_identity_effective").stdout == "personal@example.org\n"


def test_effective_after_set_is_the_github_address(home):
    bash(home, f'github_identity_set "{NOREPLY}"')
    assert bash(home, "github_identity_effective").stdout == f"{NOREPLY}\n"


def test_effective_names_the_forms_a_partial_rule_misses(home):
    key = "includeIf.hasconfig:remote.*.url:https://github.com/**.path"
    subprocess.run(["git", "config", "-f", str(home / ".gitconfig-github"), "user.email", NOREPLY],
                   check=True, env={"PATH": os.environ["PATH"], "HOME": str(home)})
    bash(home, f'git config --global "{key}" "$GITHUB_IDENTITY_PATH"')
    out = bash(home, "github_identity_effective").stdout
    assert out.startswith("differs: ")
    assert "https://github.com/o/r" in out and "git@github.com:o/r.git" in out


def test_report_ok_for_a_noreply_address(home):
    bash(home, f'github_identity_set "{NOREPLY}"')
    assert bash(home, "github_identity_report").stdout == f"ok: commits in GitHub repositories carry {NOREPLY}\n"


def test_report_without_address_says_how_to_set_one(home):
    out = bash(home, "github_identity_report").stdout
    assert out.startswith("ok: git has no e-mail address for GitHub repositories")
    assert "setup-user.sh --github-email ADDRESS" in out


def test_report_warns_for_a_personal_address(home):
    bash(home, 'github_identity_set "me@example.org"')
    out = bash(home, "github_identity_report").stdout
    assert out.startswith("warn: commits in GitHub repositories carry me@example.org, not a GitHub noreply")


def test_report_warns_when_a_later_global_email_overrides_the_rule(home):
    bash(home, f'github_identity_set "{NOREPLY}"')
    with (home / ".gitconfig").open("a") as f:
        f.write("[user]\n\temail = late@example.org\n")
    out = bash(home, "github_identity_report").stdout
    assert out.startswith(f"warn: ~/.gitconfig-github names {NOREPLY}, but commits")
    assert "late@example.org" in out


def test_report_warns_for_a_partial_rule(home):
    key = "includeIf.hasconfig:remote.*.url:https://github.com/**.path"
    bash(home, f'git config --global "{key}" "$GITHUB_IDENTITY_PATH"; '
               f'git config -f "$GITHUB_IDENTITY_FILE" user.email "{NOREPLY}"')
    assert bash(home, "github_identity_report").stdout.startswith(
        "warn: commits in GitHub repositories carry an address that depends on how the remote")


def test_undo_removes_the_entries_and_keeps_the_file(home):
    (home / ".gitconfig").write_text("[user]\n\tname = Someone\n")
    bash(home, f'github_identity_set "{NOREPLY}"')
    out = bash(home, "github_identity_undo").stdout
    assert out.startswith(">> removed the GitHub e-mail rule")
    assert "includeIf" not in (home / ".gitconfig").read_text()
    assert "name = Someone" in (home / ".gitconfig").read_text()
    assert (home / ".gitconfig-github").exists()


def test_undo_removes_entries_written_with_the_full_path(home):
    key = "includeIf.hasconfig:remote.*.url:https://github.com/**.path"
    bash(home, f'git config --global "{key}" "$GITHUB_IDENTITY_FILE"')
    bash(home, "github_identity_undo")
    assert "includeIf" not in (home / ".gitconfig").read_text()


def test_undo_leaves_a_foreign_entry_and_says_nothing(home):
    key = "includeIf.hasconfig:remote.*.url:https://github.com/**.path"
    bash(home, f'git config --global "{key}" "/elsewhere/config"')
    assert bash(home, "github_identity_undo").stdout == ""
    assert "/elsewhere/config" in (home / ".gitconfig").read_text()
