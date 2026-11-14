"""Tests of personal_data.py. All names, addresses and ids here are invented."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import personal_data

HERE = Path(__file__).parent
SCRIPT = HERE / "personal_data.py"
GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
ADDR = "alice@mail-lab.edu"  # an address at a domain that is not reserved
HOME = "/home/alice"


def git(repo, *args, name="Test Author", email="test@users.noreply.github.com"):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", f"user.name={name}", "-c", f"user.email={email}",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, env=GIT_ENV, text=True,
    ).stdout.strip()


def commit(repo, files, message="update", links=None, **who):
    """Write `files` ({path: text or bytes, None deletes}) and `links` ({path: target}) in
    the repo at `repo` (created on the first call) and commit them."""
    if not (repo / ".git").exists():
        git(repo, "init", "-q", "-b", "main")
    for path, content in files.items():
        if content is None:
            (repo / path).unlink()
            continue
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(content if isinstance(content, bytes) else content.encode())
    for path, target in (links or {}).items():
        (repo / path).symlink_to(target)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, **who)


def run(repo, *args, cwd=None):
    """Run the check script in a subprocess, on `repo` unless `cwd` is given."""
    where = [] if cwd else ["--repo", str(repo)]
    return subprocess.run(
        [sys.executable, str(SCRIPT), *where, *args],
        capture_output=True, text=True, env=GIT_ENV, cwd=cwd,
    )


def names(result):
    return [line.split()[-1] for line in result.stdout.splitlines()]


def head(repo):
    return git(repo, "rev-parse", "--short=12", "HEAD")


# One hit and the non-hits per pattern: (pattern name, text that hits, texts that do not).
CASES = [
    ("email", f"mail {ADDR} now", [
        "mail <user>@<host> now", "mail alice@<host> now", "mail bot@users.noreply.github.com",
        "Co-Authored-By: Name <noreply@anthropic.com>", "committer GitHub <noreply@github.com>",
        "41898282+github-actions[bot]@users.noreply.github.com", "pkg@1.2.3", "uses: org/act@v4.3.1",
        "alice@example.com", "alice@example.org", "alice@example.net", "alice@mail.example.org",
        "alice@host.example", "alice@host.invalid", "alice@host.test"]),
    ("nersc-project", "salloc -A m1234", [
        "salloc -A <project>", "salloc -A m12345", "key deadbeefm1234", "key Xm1234", "m1234x",
        "1m1234"]),
    ("nersc-project", "salloc -A m1234_g", []),
    ("delta-account", "-A abcd-delta-gpu", [
        "-A <project>-delta-gpu", "-A *-delta-cpu", "-A project-delta-gpu", "-A abcd-delta-gpux"]),
    ("delta-account", "-A abcd-dtai-gh", ["-A <project>-dtai-gh", "-A abcd-dtai-ghx"]),
    ("naiss-project", "project naiss2025-22-33", ["project naiss2025-<n>-<n>", "naiss2025-22"]),
    ("naiss-project", "project snic2021-22-33", ["project snic2021-<n>-<n>"]),
    ("naiss-project", "project NAISS 2025/22-33", ["project NAISS 2025/<n>-<n>", "NAISS 2025/22"]),
    ("naiss-project", "project NAISS2025-22-33", []),
    ("naiss-project", "project SNIC 2022/1-2", []),
    ("lumi-project", "/scratch/project_465000123", [
        "project_<id>", "project_46", "project_4651234567", "project_46123456", "project_470000123"]),
    ("lumi-project", "/scratch/project_462000123", []),
    ("access-allocation", "allocation ABC123456", [
        "allocation ABCD123456", "allocation ABC12345", "allocation ABC1234567", "allocation abc123456",
        "allocation <ACCESS-ID>"]),
    ("path", f"cd {HOME}/work", [
        "cd /home/<user>/work", "cd /home/$USER", "cd /home/${USER}/x", "cd /home/*/x", "cd /home/~",
        "cd /home/", "cd a/home/alice", "see https://lab.edu/home/alice", "cd $HOME/home/alice",
        "cd ../home/alice"]),
    ("path", "cd /Users/alice/work", ["cd /Users/<user>"]),
    ("path", "open file:///home/alice/x", []),
    ("path", "cd //home/alice", []),
    ("path", "cd /global/homes/a/alice", ["cd /global/homes/x/<user>", "cd /global/homes/x/$USER"]),
    ("path", "cd /pscratch/sd/a/alice/run", ["cd /pscratch/sd/<x>/<user>", "cd /pscratch/sd/p/${USER}"]),
    ("path", "cd /u/alice", ["cd /u/<user>", "cd /usr/local"]),
    ("path", "cd /users/alice", ["cd /users/<user>"]),
    ("path", "cd /cfs/klemming/home/a/alice", ["cd /cfs/klemming/home/x/<user>"]),
    ("path", "cd /cfs/klemming/scratch/a/alice", []),
    ("path", "cd /global/cfs/cdirs/proj", ["cd /global/cfs/cdirs/<project>"]),
    ("path", r"literal backslash n: /home/bob\n", []),
]


@pytest.mark.parametrize("pattern,hit,non_hits", CASES)
def test_pattern(tmp_path, pattern, hit, non_hits):
    commit(tmp_path, {"hit.txt": f"ok\n{hit}\n", **{f"non{i}.txt": t for i, t in enumerate(non_hits)}})
    result = run(tmp_path)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"hit.txt:2: {pattern}"]


def test_clean_tree_exits_zero(tmp_path):
    commit(tmp_path, {"a.txt": "nothing to see\n"})
    result = run(tmp_path)
    assert (result.returncode, result.stdout) == (0, "")


def test_tree_mode_scans_committed_head_not_the_working_tree(tmp_path):
    commit(tmp_path, {"a.txt": f"{ADDR}\n"})
    (tmp_path / "a.txt").write_text("ok\n")  # unstaged edit hides nothing
    (tmp_path / "untracked.txt").write_text(f"{HOME}\n")
    git(tmp_path, "add", "untracked.txt")
    result = run(tmp_path)
    assert result.stdout.splitlines() == ["a.txt:1: email"]


def test_tree_mode_scans_from_the_top_level_in_a_subdirectory(tmp_path):
    commit(tmp_path, {"top.txt": f"{ADDR}\n", "sub/a.txt": "ok\n"})
    result = run(tmp_path, cwd=tmp_path / "sub")
    assert result.stdout.splitlines() == ["top.txt:1: email"]
    assert run(tmp_path / "sub").stdout.splitlines() == ["top.txt:1: email"]


def test_symlink_target_is_scanned(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, links={"link": f"{HOME}/data"})
    assert run(tmp_path).stdout.splitlines() == ["link:1: path"]
    assert run(tmp_path, "--history").stdout.split()[1:] == ["link", "path"]


def test_binary_file_is_scanned_and_reported_without_a_line(tmp_path):
    commit(tmp_path, {"doc.pdf": b"%PDF\0\x01 /Author (" + ADDR.encode() + b") \xe9\0\n/x (" + ADDR.encode() + b")"})
    assert run(tmp_path).stdout.splitlines() == ["doc.pdf:?: email"]
    assert run(tmp_path, "--history").stdout.split()[1:] == ["doc.pdf", "email"]


def test_utf16_file_with_bom_and_latin1_text_are_scanned(tmp_path):
    commit(tmp_path, {"u16.txt": f"ok\ncontact {ADDR}\n".encode("utf-16"),
                      "l1.txt": f"caf\xe9\ncontact {ADDR}\n".encode("latin-1")})
    assert sorted(run(tmp_path).stdout.splitlines()) == ["l1.txt:2: email", "u16.txt:2: email"]


def test_output_has_no_matched_text(tmp_path):
    commit(tmp_path, {"a.txt": f"{ADDR} m1234 {HOME}\n"})
    result = run(tmp_path)
    assert names(result) == ["email", "nersc-project", "path"]
    assert not any(t in result.stdout + result.stderr for t in ("alice", "mail-lab", "m1234"))


def test_internal_error_exits_two_without_a_traceback(tmp_path, monkeypatch, capsys):
    commit(tmp_path, {"a.txt": "ok\n"})
    monkeypatch.setattr(personal_data, "tree_hits", lambda *a: 1 / 0)
    assert personal_data.main(["--repo", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "ZeroDivisionError" in err and "Traceback" not in err


def test_main_in_process(tmp_path, capsys):
    commit(tmp_path, {"a.txt": f"{ADDR}\n"})
    assert personal_data.main(["--repo", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "a.txt:1: email\n"


# --- allow-lists --------------------------------------------------------------------

def allow_file(tmp_path, *entries):
    path = tmp_path / "allow.txt"
    path.write_text("# comment\n\n" + "\n".join("\t".join(e) for e in entries) + "\n")
    return str(path)


def test_allow_entry_suppresses_exactly_its_path_pattern_and_text(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit(repo, {
        "docs/a.txt": f"contact {ADDR}\n",
        "docs/b.txt": f"contact {ADDR}\n",
        "docs/c.txt": "contact bob@mail-lab.edu\n",
        "docs/d.txt": f"contact {ADDR} and {HOME}\n",
    })
    allow = allow_file(tmp_path, ("docs/[acd].txt", "email", ADDR))
    result = run(repo, "--allow", allow)
    assert result.returncode == 1
    assert sorted(result.stdout.splitlines()) == ["docs/b.txt:1: email", "docs/c.txt:1: email", "docs/d.txt:1: path"]


def test_allow_entry_for_another_pattern_does_not_suppress(tmp_path):
    commit(tmp_path, {"a.txt": f"{ADDR}\n"})
    assert names(run(tmp_path, "--allow", allow_file(tmp_path, ("a.txt", "path", ADDR)))) == ["email"]


def test_tracked_allow_file_applies_below_its_own_directory_only(tmp_path):
    commit(tmp_path, {
        "a.txt": f"{ADDR}\n",
        "personal-data-allow.txt": f"a.txt\temail\t{ADDR}\n",
        "sub/a.txt": f"{ADDR}\n",
        "sub/personal-data-allow.txt": f"a.txt\temail\t{ADDR}\n",
        "sub/deep/a.txt": f"{ADDR}\n",
        "other/a.txt": f"{ADDR}\n",
    })
    # root entry names a.txt at the top only; sub's names sub/a.txt only; the rest hit
    assert sorted(run(tmp_path).stdout.splitlines()) == ["other/a.txt:1: email", "sub/deep/a.txt:1: email"]


def test_explicit_allow_file_globs_are_relative_to_the_top_level(tmp_path):
    commit(tmp_path, {"sub/a.txt": f"{ADDR}\n"})
    assert run(tmp_path, "--allow", allow_file(tmp_path, ("sub/a.txt", "email", ADDR))).returncode == 0
    assert run(tmp_path, "--allow", allow_file(tmp_path, ("a.txt", "email", ADDR))).returncode == 1


def test_allow_file_is_scanned_hits_outside_a_current_entry_text_remain(tmp_path):
    commit(tmp_path, {
        "personal-data-allow.txt": f"# contact {ADDR}\nsub/m1234.txt\temail\t{ADDR}\n*.txt\tpath\t{HOME}\n",
        "a.txt": "ok\n",
    })
    # the entries' texts are allowed; the comment and the glob field are scanned
    assert run(tmp_path).stdout.splitlines() == [
        "personal-data-allow.txt:1: email", "personal-data-allow.txt:2: nersc-project"]


def test_allow_file_entry_text_is_allowed_only_under_its_own_pattern_name(tmp_path):
    commit(tmp_path, {"personal-data-allow.txt": f"a.txt\tpath\t{ADDR}\n"})
    assert run(tmp_path).stdout.splitlines() == ["personal-data-allow.txt:1: email"]


def test_removed_allow_entry_still_hits_in_history(tmp_path):
    commit(tmp_path, {"personal-data-allow.txt": f"a.txt\temail\t{ADDR}\n"}, message="one")
    old = head(tmp_path)
    commit(tmp_path, {"personal-data-allow.txt": "# none\n"}, message="two")
    assert run(tmp_path).returncode == 0
    result = run(tmp_path, "--history")
    # the adding and the removing commit both carry it
    assert len(result.stdout.splitlines()) == 2
    assert f"{old} personal-data-allow.txt email" in result.stdout.splitlines()


def test_vendored_copy_of_this_repository_in_core_needs_no_consumer_entries(tmp_path):
    files = ["checks/personal_data.py", "checks/test_personal_data.py", "personal-data-allow.txt"]
    for rel in files:
        (tmp_path / "core" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE.parent / rel, tmp_path / "core" / rel)
    commit(tmp_path, {"README.md": "consumer\n"})
    assert run(tmp_path).stdout == ""
    # the entries do not leak out of core/
    (tmp_path / "x.txt").write_text(f"{ADDR}\n")
    commit(tmp_path, {"x.txt": f"{ADDR}\n"})
    assert run(tmp_path).stdout.splitlines() == ["x.txt:1: email"]


@pytest.mark.parametrize("line", [
    "a.txt\temail", "a.txt\temail\t", "a.txt\tnope\ttext", "a.txt email text"])
def test_bad_allow_line_is_usage_error(tmp_path, line):
    commit(tmp_path, {"a.txt": "x\n"})
    allow = tmp_path / "allow.txt"
    allow.write_text(f"# ok\n{line}\n")
    result = run(tmp_path, "--allow", str(allow))
    assert result.returncode == 2
    assert f"{allow}:2" in result.stderr


def test_bad_line_in_a_tracked_allow_file_names_its_path(tmp_path):
    commit(tmp_path, {"sub/personal-data-allow.txt": "a.txt\temail\n"})
    result = run(tmp_path)
    assert result.returncode == 2 and "sub/personal-data-allow.txt:1" in result.stderr


def test_unreadable_files_and_non_repos_are_usage_errors(tmp_path):
    commit(tmp_path, {"a.txt": "x\n"})
    assert run(tmp_path, "--allow", str(tmp_path / "missing.txt")).returncode == 2
    assert run(tmp_path / "nonexistent").returncode == 2
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00 not utf-8\n")
    assert run(tmp_path, "--allow", str(bad)).returncode == 2
    assert run(tmp_path, "--extra", str(bad)).returncode == 2
    commit(tmp_path, {"personal-data-allow.txt": b"\xff\xfe\x00 not utf-8\n"})
    result = run(tmp_path)
    assert result.returncode == 2 and "personal-data-allow.txt" in result.stderr


# --- extra literals -----------------------------------------------------------------

def extra_file(tmp_path, *literals):
    path = tmp_path / "extra.txt"
    path.write_text("# private\n\n" + "\n".join(literals) + "\n")
    return str(path)


def test_extra_literal_hits_case_insensitively_as_substring(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit(repo, {"a.txt": "by ALICE EXAMPLE\n", "b.txt": "path /x/aliceexample2/y\n", "c.txt": "Alice Other\n"})
    result = run(repo, "--extra", extra_file(tmp_path, "Alice Example", "aliceexample"))
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["a.txt:1: extra:3", "b.txt:1: extra:4"]
    assert not any(t in (result.stdout + result.stderr).lower() for t in ("alice", "example"))


def test_extra_literal_matches_across_unicode_normalisation_forms(tmp_path):
    commit(tmp_path, {"a.txt": "by Zoë Example\n", "b.txt": "by Zoë Example\n"})
    for literal in ("Zoë Example", "Zoë Example"):
        result = run(tmp_path, "--extra", extra_file(tmp_path, literal))
        assert result.stdout.splitlines() == ["a.txt:1: extra:3", "b.txt:1: extra:3"]


def test_extra_hit_is_suppressed_by_context_entry_only_there(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit(repo, {
        "LICENSE": "Copyright (c) 2026, Alice Example\n",
        "README.md": "see github.com/aexample/core and Alice Example\n",
        "other.md": "Copyright (c) 2026, Alice Example\n",
    })
    allow = allow_file(tmp_path,
                       ("LICENSE", "extra", "Copyright (c) 2026, Alice Example"),
                       ("README.md", "extra", "github.com/aexample/core"))
    result = run(repo, "--extra", extra_file(tmp_path, "Alice Example", "aexample"), "--allow", allow)
    assert sorted(result.stdout.splitlines()) == ["README.md:1: extra:3", "other.md:1: extra:3"]


@pytest.mark.parametrize("literal", ["ab", "x"])
def test_short_extra_literal_is_usage_error(tmp_path, literal):
    commit(tmp_path, {"a.txt": "x\n"})
    extra = extra_file(tmp_path, "Alice Example", literal)
    result = run(tmp_path, "--extra", extra)
    assert result.returncode == 2
    assert f"{extra}:4" in result.stderr


# --- history ------------------------------------------------------------------------

def test_history_finds_hit_only_in_deleted_line(tmp_path):
    commit(tmp_path, {"a.txt": f"ok\n{ADDR}\n"}, message="add")
    commit(tmp_path, {"a.txt": "ok\n"}, message="remove")
    assert run(tmp_path).returncode == 0
    result = run(tmp_path, "--history")
    assert result.returncode == 1
    # the deleting commit is reported next to the adding one
    assert len(result.stdout.splitlines()) == 2
    assert f"{head(tmp_path)} a.txt email" in result.stdout.splitlines()


def test_history_finds_hit_only_in_author_address(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, name="Test Author", email=ADDR)
    assert run(tmp_path).returncode == 0
    result = run(tmp_path, "--history")
    assert result.returncode == 1
    assert [line.split()[1:] for line in result.stdout.splitlines()] == [
        ["author", "email"], ["committer", "email"]]


def test_history_finds_committer_message_and_extra(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, message="fix for project m1234")
    git(tmp_path, "commit", "-q", "--amend", "--no-edit", "--reset-author", name="Committer Person",
        email="carol@mail-lab.edu")
    result = run(tmp_path, "--history", "--extra", extra_file(tmp_path, "Committer Person"))
    assert sorted(line.split()[1:] for line in result.stdout.splitlines()) == [
        ["author", "email"], ["author", "extra:3"], ["committer", "email"], ["committer", "extra:3"],
        ["message", "nersc-project"]]


def test_history_noreply_address_of_a_named_person_still_hits_extra(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, name="Alice Example", email="1+aexample@users.noreply.github.com")
    result = run(tmp_path, "--history", "--extra", extra_file(tmp_path, "Alice Example"))
    assert [line.split()[1:] for line in result.stdout.splitlines()] == [
        ["author", "extra:3"], ["committer", "extra:3"]]
    identity = "Alice Example <1+aexample@users.noreply.github.com>"
    allow = allow_file(tmp_path, ("author", "extra", identity), ("committer", "extra", identity))
    args = ("--history", "--extra", extra_file(tmp_path, "Alice Example"), "--allow", allow)
    assert run(tmp_path, *args).returncode == 0
    commit(tmp_path, {"b.txt": "ok\n"}, name="Alice Example", email="2+other@users.noreply.github.com")
    assert run(tmp_path, *args).returncode == 1


def test_history_github_web_merge_committer_is_not_a_hit(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, name="GitHub", email="noreply@github.com")
    assert run(tmp_path, "--history").returncode == 0


def test_history_output_never_contains_the_line(tmp_path):
    commit(tmp_path, {"a.txt": f"secret {ADDR} {HOME}\n"}, message=f"m1234 {ADDR}")
    result = run(tmp_path, "--history")
    assert result.returncode == 1
    assert not any(t in result.stdout + result.stderr for t in ("secret", "alice", "mail-lab", "m1234"))


def test_history_content_line_looking_like_a_header(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"})
    commit(tmp_path, {"a.txt": f"ok\n+++ b/other.txt {ADDR}\n"})
    result = run(tmp_path, "--history")
    assert [line.split()[1:] for line in result.stdout.splitlines()] == [["a.txt", "email"]]


def test_history_allow_applies_to_diff_paths(tmp_path):
    commit(tmp_path, {"LICENSE": "Copyright (c) 2026, Alice Example\n"})
    extra = extra_file(tmp_path, "Alice Example")
    assert run(tmp_path, "--history", "--extra", extra).returncode == 1
    allow = allow_file(tmp_path, ("LICENSE", "extra", "Copyright (c) 2026, Alice Example"))
    assert run(tmp_path, "--history", "--extra", extra, "--allow", allow).returncode == 0


def test_history_includes_changes_made_in_a_merge_commit(tmp_path):
    commit(tmp_path, {"a.txt": "base\n"})
    git(tmp_path, "checkout", "-q", "-b", "side")
    commit(tmp_path, {"b.txt": "side\n"})
    git(tmp_path, "checkout", "-q", "main")
    commit(tmp_path, {"c.txt": "main\n"})
    git(tmp_path, "merge", "-q", "--no-ff", "--no-commit", "side")
    commit(tmp_path, {"d.txt": f"{ADDR}\n"}, message="merge")
    assert run(tmp_path, "--history").stdout.splitlines() == [f"{head(tmp_path)} d.txt email"]


def test_history_scans_annotated_tags_not_lightweight_ones(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"})
    git(tmp_path, "tag", "light")
    git(tmp_path, "tag", "-a", "v1", "-m", f"release by {ADDR} m1234", name="Bob Tagger", email="bob@mail-lab.edu")
    tag = git(tmp_path, "rev-parse", "--short=12", "v1")
    assert sorted(run(tmp_path, "--history").stdout.splitlines()) == [
        f"{tag} tag email", f"{tag} tag nersc-project"]


def test_history_survives_separator_bytes_in_a_message(tmp_path):
    commit(tmp_path, {"a.txt": "ok\n"}, message=f"one\x1etwo\n\n{ADDR}\x1e\n")
    result = run(tmp_path, "--history")
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert result.stdout.split()[1:] == ["message", "email"]
    commit(tmp_path, {"a.txt": "ok2\n"}, message="x\x1ey")
    assert len(run(tmp_path, "--history").stdout.splitlines()) == 1


def test_history_message_entry_suppresses_exactly_its_text(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit(repo, {"a.txt": "ok\n"}, message="Merge pull request #1 from alicex/topic")
    extra = extra_file(tmp_path, "alicex", "bobx")
    allow = allow_file(tmp_path, ("message", "extra", "from alicex/"))
    args = ("--history", "--extra", extra, "--allow", allow)
    assert run(repo, "--history", "--extra", extra).returncode == 1
    assert run(repo, *args).returncode == 0
    commit(repo, {"b.txt": "ok\n"}, message="Merge pull request #2 from alicex/topic\n\nwith bobx")
    assert [line.split()[1:] for line in run(repo, *args).stdout.splitlines()] == [["message", "extra:4"]]
