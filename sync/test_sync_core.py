"""Tests of sync-core.sh on throwaway repositories. The upstream is a local copy of this
tree committed as a repository, reached through a file:// URL; no test needs the network."""

import filecmp
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent
SYNC = HERE / "sync-core.sh"
GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test Author",
         "-c", "user.email=test@users.noreply.github.com", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, env=GIT_ENV, text=True,
    ).stdout.strip()


def commit(repo, message="update"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def upstream(tmp_path):
    """A repository holding the current tree of this repository (tracked and new files)."""
    repo = tmp_path / "upstream"
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True, capture_output=True, env=GIT_ENV, text=True,
    ).stdout.split("\0")
    for name in filter(None, listed):
        if (ROOT / name).is_file():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_bytes((ROOT / name).read_bytes())
            (repo / name).chmod((ROOT / name).stat().st_mode)
    commit(repo, "initial")
    return repo


@pytest.fixture
def consumer(tmp_path):
    repo = tmp_path / "consumer"
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    (repo / "README.md").write_text("consumer\n")
    commit(repo, "initial")
    return repo


def run(consumer, upstream, *args, script=SYNC, cwd=None):
    env = {**GIT_ENV, "HPCENV_CORE_URL": f"file://{upstream}"}
    return subprocess.run(["bash", str(script), *args], cwd=cwd or consumer, env=env,
                          capture_output=True, text=True)


def sync(consumer, upstream, ref="main", **kw):
    result = run(consumer, upstream, ref, **kw)
    assert result.returncode == 0, result.stderr
    return result


def files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_sync_makes_core_equal_to_archive_of_ref(consumer, upstream, tmp_path):
    sync(consumer, upstream)
    expected = tmp_path / "expected"
    expected.mkdir()
    archive = tmp_path / "up.tar"
    git(upstream, "archive", "-o", str(archive), "main")
    with tarfile.open(archive) as tar:
        tar.extractall(expected, filter="data")
    sha = git(upstream, "rev-parse", "main")
    assert (consumer / "core" / "CORE_COMMIT").read_text() == sha + "\n"
    assert files(consumer / "core") == sorted(files(expected) + ["CORE_COMMIT"])
    assert not filecmp.cmpfiles(expected, consumer / "core", files(expected), shallow=False)[1]
    assert os.access(consumer / "core" / "sync" / "sync-core.sh", os.X_OK)


def test_sync_leaves_the_change_uncommitted(consumer, upstream):
    head = git(consumer, "rev-parse", "HEAD")
    sync(consumer, upstream)
    assert git(consumer, "rev-parse", "HEAD") == head
    assert git(consumer, "status", "--porcelain", "--untracked-files=all").splitlines()[0].startswith("?? core/")


def test_sync_from_a_subdirectory_uses_the_top_level(consumer, upstream):
    (consumer / "sub").mkdir()
    sync(consumer, upstream, cwd=consumer / "sub")
    assert (consumer / "core" / "CORE_COMMIT").exists()


def test_sync_with_C_from_elsewhere(consumer, upstream, tmp_path):
    result = run(consumer, upstream, "-C", str(consumer), "main", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (consumer / "core" / "CORE_COMMIT").exists()


def test_second_run_at_the_same_ref_changes_nothing(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    sync(consumer, upstream)
    assert git(consumer, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("change", ["unstaged", "staged", "untracked"])
def test_sync_refuses_local_change_in_core(consumer, upstream, change):
    sync(consumer, upstream)
    commit(consumer, "core")
    target = consumer / "core" / "README.md"
    if change == "untracked":
        target = consumer / "core" / "extra.txt"
    target.write_text("local edit\n")
    if change == "staged":
        git(consumer, "add", "core/README.md")
    result = run(consumer, upstream, "main")
    assert result.returncode != 0
    assert "core/" in result.stderr and "local changes" in result.stderr
    assert target.read_text() == "local edit\n"


def test_sync_moves_to_a_later_commit_and_drops_removed_files(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    (upstream / "docs" / "LICENSE").unlink()
    (upstream / "new.txt").write_text("new\n")
    commit(upstream, "second")
    sync(consumer, upstream)
    assert (consumer / "core" / "CORE_COMMIT").read_text() == git(upstream, "rev-parse", "main") + "\n"
    assert (consumer / "core" / "new.txt").exists()
    assert not (consumer / "core" / "docs" / "LICENSE").exists()


def test_sync_by_tag_and_by_full_sha(consumer, upstream):
    git(upstream, "tag", "v1")
    sha = git(upstream, "rev-parse", "HEAD")
    (upstream / "new.txt").write_text("new\n")
    commit(upstream, "second")
    sync(consumer, upstream, "v1")
    assert (consumer / "core" / "CORE_COMMIT").read_text() == sha + "\n"
    assert not (consumer / "core" / "new.txt").exists()
    commit(consumer, "core")
    sync(consumer, upstream, git(upstream, "rev-parse", "main"))
    assert (consumer / "core" / "new.txt").exists()


def test_unknown_ref_fails_and_leaves_core_alone(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    result = run(consumer, upstream, "no-such-ref")
    assert result.returncode != 0 and "no-such-ref" in result.stderr
    assert git(consumer, "status", "--porcelain", "--untracked-files=all") == ""


def test_vendored_copy_can_sync_itself(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    with open(upstream / "sync" / "sync-core.sh", "a") as f:
        f.write("# changed upstream\n")
    commit(upstream, "second")
    result = run(consumer, upstream, "main", script=consumer / "core" / "sync" / "sync-core.sh")
    assert result.returncode == 0, result.stderr
    assert (consumer / "core" / "sync" / "sync-core.sh").read_text().endswith("# changed upstream\n")


def test_bad_usage(consumer, upstream):
    for args in [(), ("main", "extra"), ("--check", "main"), ("--bogus",)]:
        result = run(consumer, upstream, *args)
        assert result.returncode != 0 and "usage" in result.stderr


def test_check_is_green_after_a_sync(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    result = run(consumer, upstream, "--check")
    assert result.returncode == 0, result.stderr


def test_check_is_red_after_an_edit_and_names_the_path(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    (consumer / "core" / "README.md").write_text("edited\n")
    (consumer / "core" / "added.txt").write_text("added\n")
    (consumer / "core" / "docs" / "LICENSE").unlink()
    result = run(consumer, upstream, "--check")
    assert result.returncode != 0
    for path in ["core/README.md", "added.txt", "LICENSE"]:
        assert path in result.stderr
    git(consumer, "checkout", "--", "core")
    git(consumer, "clean", "-fdq", "core")
    assert run(consumer, upstream, "--check").returncode == 0


def test_check_judges_against_core_commit_not_upstream_main(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    (upstream / "new.txt").write_text("new\n")
    commit(upstream, "second")
    assert run(consumer, upstream, "--check").returncode == 0


def test_check_without_core_commit_is_an_error(consumer, upstream):
    result = run(consumer, upstream, "--check")
    assert result.returncode != 0 and "CORE_COMMIT" in result.stderr
    sync(consumer, upstream)
    (consumer / "core" / "CORE_COMMIT").write_text("main\n")
    result = run(consumer, upstream, "--check")
    assert result.returncode != 0 and "CORE_COMMIT" in result.stderr


def test_personal_data_check_from_the_consumer_top_level_is_clean(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    result = subprocess.run([sys.executable, "core/checks/personal_data.py"], cwd=consumer,
                            env=GIT_ENV, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("args", [("main",), ("--check",)])
def test_outside_a_git_repository_nothing_is_touched(tmp_path, upstream, args):
    plain = tmp_path / "plain"
    (plain / "core").mkdir(parents=True)
    (plain / "core" / "mine").write_text("precious\n")
    result = run(plain, upstream, *args, cwd=plain)
    assert result.returncode != 0 and "not in a git repository" in result.stderr
    assert (plain / "core" / "mine").read_text() == "precious\n"
    result = run(plain, upstream, "-C", str(plain), *args, cwd=tmp_path)
    assert result.returncode != 0 and "not in a git repository" in result.stderr
    assert (plain / "core" / "mine").read_text() == "precious\n"


@pytest.mark.parametrize("args", [("main",), ("--check",)])
def test_core_that_is_a_symlink_is_refused(consumer, upstream, tmp_path, args):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "mine").write_text("precious\n")
    (consumer / "core").symlink_to(elsewhere)
    commit(consumer, "link")
    result = run(consumer, upstream, *args)
    assert result.returncode != 0 and "symbolic link" in result.stderr
    assert (consumer / "core").is_symlink()
    assert (elsewhere / "mine").read_text() == "precious\n"


@pytest.mark.parametrize("args", [("main",), ("--check",)])
def test_core_that_is_a_submodule_is_refused(consumer, upstream, args):
    git(consumer, "update-index", "--add", "--cacheinfo", f"160000,{git(upstream, 'rev-parse', 'HEAD')},core")
    git(consumer, "commit", "-q", "-m", "submodule")
    result = run(consumer, upstream, *args)
    assert result.returncode != 0 and "submodule" in result.stderr
    assert not (consumer / "core").exists()


def test_check_says_when_the_pinned_commit_is_gone_upstream(consumer, upstream):
    sync(consumer, upstream)
    commit(consumer, "core")
    (consumer / "core" / "CORE_COMMIT").write_text("0" * 40 + "\n")
    commit(consumer, "pin a commit upstream does not have")
    result = run(consumer, upstream, "--check")
    assert result.returncode != 0 and "not available" in result.stderr and "0" * 40 in result.stderr
