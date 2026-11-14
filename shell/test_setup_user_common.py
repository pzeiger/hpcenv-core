"""Tests of setup-user-common.sh in a temporary HOME, driven by an invented cluster script.

`example-setup-user.sh`, written into tmp_path, has the shape of a cluster's setup-user.sh:
usage comment, `set -euo pipefail`, source the common file, parse, undo, begin, a cluster
part (here a project name and a stub env.sh), then the shared checks and the summary."""

import os
import subprocess
from pathlib import Path

import pytest

COMMON = Path(__file__).parent / "setup-user-common.sh"
NOREPLY = "12345+someone@users.noreply.github.com"

EXAMPLE = r'''#!/bin/bash
# example-setup-user.sh: setup for the invented Examplecluster.
#
#     example-setup-user.sh --project NAME   # name the project
#     example-setup-user.sh --check          # report only
#
# A second paragraph.
set -euo pipefail

. "$COMMON"
SETUP_USER_NAME=example-env
SETUP_USER_PROJECT_NOUN="a name"
setup_user_parse_args "$@"
setup_user_validate
ENVSH="$FAKE/env.sh"
RC="$HOME/.bashrc"
MARK="# >>> example-env (examplecluster) >>>"
ENDMARK="# <<< example-env (examplecluster) <<<"
if [ "$UNDO" = 1 ]; then setup_user_undo; fi
setup_user_begin "example-env user setup: Examplecluster"

echo "1. project"
if [ -z "$PROJ" ]; then
    warn "no project: run with --project NAME"
    setup_user_stop
fi
ok "$PROJ"
echo
echo "2. shell startup"
if [ -f "$RC" ] && grep -qxF "$MARK" "$RC"; then
    ok "$RC already has the block"
elif [ "$CHECK" = 1 ]; then
    warn "$RC has no block (run without --check to add it)"
else
    setup_user_add_block EXAMPLE_PROJECT "$PROJ" Examplecluster
fi
echo
echo "3. checks"
setup_user_cache_dir "$FAKE/cache"
setup_user_check_apptainer
setup_user_github_report
more "note"
setup_user_summary
'''


@pytest.fixture
def world(tmp_path):
    """HOME, a fake root with a stub env.sh, and a bin directory with an apptainer stub."""
    for d in ("home", "fake", "bin"):
        (tmp_path / d).mkdir()
    (tmp_path / "fake" / "env.sh").write_text("# stub\n")
    (tmp_path / "example-setup-user.sh").write_text(EXAMPLE)
    return tmp_path


def run(world, args=(), body=None, apptainer=True):
    """Run the example script (or `body`, with the common file sourced) in the temporary HOME."""
    bindir = world / "bin"
    stub = bindir / "apptainer"
    if apptainer and not stub.exists():
        stub.write_text("#!/bin/bash\n")
        stub.chmod(0o755)
    if not apptainer and stub.exists():
        stub.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "XDG_"))}
    env.update(HOME=str(world / "home"), GIT_CONFIG_NOSYSTEM="1", COMMON=str(COMMON),
               FAKE=str(world / "fake"), PATH=f"{bindir}:{os.environ['PATH']}")
    if body is None:
        cmd = ["bash", str(world / "example-setup-user.sh"), *args]
    else:
        prelude = (f'set -euo pipefail\n. "{COMMON}"\nSETUP_USER_NAME=example-env\n'
                   f'SETUP_USER_PROJECT_NOUN="a name"\nRC="$HOME/.bashrc"\n'
                   f'MARK="# >>> m >>>"\nENDMARK="# <<< m <<<"\nENVSH=/x/env.sh\n')
        cmd = ["bash", "-c", prelude + body]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=world)


def rc_file(world):
    return world / "home" / ".bashrc"


def test_fresh_run_writes_the_block_and_reports(world):
    result = run(world, ["--project", "p1"])
    assert result.returncode == 0, result.stderr
    cache = world / "fake" / "cache"
    assert result.stdout == f"""example-env user setup: Examplecluster

1. project
  ok    p1

2. shell startup
  did   added the block to {rc_file(world)}
  did   run '. {rc_file(world)}' or open a new shell to pick it up now

3. checks
  did   created {cache}
  ok    apptainer is on PATH
  ok    git has no e-mail address for GitHub repositories (setup-user.sh --github-email ADDRESS sets one)
        note

All good.
"""
    assert rc_file(world).read_text() == f"""
# >>> example-env (examplecluster) >>>
# Added by setup-user.sh. Safe to source anywhere: env.sh is silent,
# idempotent, and does nothing off Examplecluster.
export EXAMPLE_PROJECT=p1
if [ -r "{world / 'fake' / 'env.sh'}" ]; then . "{world / 'fake' / 'env.sh'}"; fi
# <<< example-env (examplecluster) <<<
"""
    assert cache.is_dir()


def test_second_run_is_idempotent(world):
    run(world, ["--project", "p1"])
    before = rc_file(world).read_text()
    result = run(world, ["--project", "p1"])
    assert "already has the block" in result.stdout and "did   added" not in result.stdout
    assert f"ok    apptainer cache directory exists: {world / 'fake' / 'cache'}" in result.stdout
    assert rc_file(world).read_text() == before


def test_check_changes_nothing_and_counts_warnings(world):
    result = run(world, ["--project", "p1", "--check"])
    assert result.stdout.startswith("example-env user setup: Examplecluster\n"
                                    "(--check: reporting only, nothing will be changed)\n")
    assert "2 warning(s) above." in result.stdout
    assert not rc_file(world).exists() and not (world / "fake" / "cache").exists()


def test_no_project_stops_with_exit_1_and_one_warning(world):
    result = run(world)
    assert result.returncode == 1
    assert result.stdout.endswith("  warn  no project: run with --project NAME\n\n1 warning(s) above.\n")


def test_github_email_sets_the_rule_and_the_report_confirms_it(world):
    result = run(world, ["--project", "p1", "--github-email", NOREPLY])
    assert f"  did   GitHub repositories now commit as {NOREPLY} (~/.gitconfig-github)" in result.stdout
    assert f"  ok    commits in GitHub repositories carry {NOREPLY}" in result.stdout
    assert (world / "home" / ".gitconfig-github").is_file()


def test_github_email_with_check_is_not_applied(world):
    result = run(world, ["--project", "p1", "--check", "--github-email", NOREPLY])
    assert "  warn  --github-email is not applied with --check" in result.stdout
    assert not (world / "home" / ".gitconfig-github").exists()


@pytest.mark.parametrize("args, message", [
    (["--github-email"], "--github-email needs an address"),
    (["--github-email", ""], "--github-email needs an address"),
    (["--project"], "--project needs a name"),
    (["--frob"], "unknown option: --frob (try --help)"),
    (["--github-email", "nonsense"], "not an e-mail address: nonsense"),
    (["--check", "--undo"], "--check and --undo exclude each other"),
])
def test_bad_arguments_exit_1_before_anything_is_changed(world, args, message):
    result = run(world, args)
    assert (result.returncode, result.stdout, result.stderr) == (1, "", message + "\n")
    assert not rc_file(world).exists()


def test_help_prints_the_leading_comment_block(world):
    result = run(world, ["--help"])
    assert result.returncode == 0
    assert result.stdout == """example-setup-user.sh: setup for the invented Examplecluster.

    example-setup-user.sh --project NAME   # name the project
    example-setup-user.sh --check          # report only

A second paragraph.
"""
    assert run(world, ["-h"]).stdout == result.stdout


def test_undo_removes_the_block_keeps_the_rest_and_writes_a_backup(world):
    rc_file(world).write_text("alias a=b\n")
    run(world, ["--project", "p1", "--github-email", NOREPLY])
    original = rc_file(world).read_text()
    result = run(world, ["--undo"])
    assert result.returncode == 0
    assert rc_file(world).read_text() == "alias a=b\n"
    assert (world / "home" / ".bashrc.example-env-backup").read_text() == original
    assert f">> removed the example-env block from {rc_file(world)} (backup: {rc_file(world)}.example-env-backup)" in result.stdout
    assert ">> removed the GitHub e-mail rule" in result.stdout
    assert "includeIf" not in (world / "home" / ".gitconfig").read_text()


def test_undo_without_a_block_or_file_says_so(world):
    assert run(world, ["--undo"]).stdout == f">> no example-env block found in {rc_file(world)}\n"
    rc_file(world).write_text("alias a=b\n")
    assert run(world, ["--undo"]).stdout == f">> no example-env block found in {rc_file(world)}\n"
    assert rc_file(world).read_text() == "alias a=b\n"


@pytest.mark.parametrize("text", [
    "# >>> example-env (examplecluster) >>>\nx\n",
    "# <<< example-env (examplecluster) <<<\n# >>> example-env (examplecluster) >>>\nx\n",
    "# >>> example-env (examplecluster) >>>\n# >>> example-env (examplecluster) >>>\nx\n"
    "# <<< example-env (examplecluster) <<<\n",
])
def test_undo_refuses_markers_that_are_not_one_start_above_one_end(world, text):
    rc_file(world).write_text(text)
    result = run(world, ["--undo"])
    assert result.returncode == 1
    assert "markers are not one start line followed by one" in result.stderr
    assert rc_file(world).read_text() == text
    assert not (world / "home" / ".bashrc.example-env-backup").exists()


def test_cache_dir_branches(world):
    cache = world / "cache1"
    out = run(world, body=f'CHECK=1; setup_user_cache_dir "{cache}"; echo "w=$WARNINGS"').stdout
    assert out == f"  warn  no apptainer cache directory yet: {cache} (run without --check to create it)\nw=1\n"
    assert not cache.exists()
    assert run(world, body=f'CHECK=0; setup_user_cache_dir "{cache}"').stdout == f"  did   created {cache}\n"
    assert run(world, body=f'CHECK=0; setup_user_cache_dir "{cache}"').stdout == \
        f"  ok    apptainer cache directory exists: {cache}\n"
    blocked = world / "file"
    blocked.write_text("")
    out = run(world, body=f'CHECK=0; setup_user_cache_dir "{blocked}/sub"; echo "w=$WARNINGS"').stdout
    assert out == f"  warn  could not create {blocked}/sub\nw=1\n"


def test_missing_apptainer_warns(world):
    result = run(world, ["--project", "p1"], apptainer=False)
    assert "  warn  apptainer is not on PATH (are you on a login node?)" in result.stdout


def test_more_continues_a_warning_without_counting_it(world):
    out = run(world, body='warn "a"; more "b"; echo "w=$WARNINGS"').stdout
    assert out == "  warn  a\n        b\nw=1\n"


def test_summary_and_stop(world):
    assert run(world, body="setup_user_summary").stdout == "\nAll good.\n"
    assert run(world, body="warn x; warn y; setup_user_summary").stdout.endswith("\n2 warning(s) above.\n")
    result = run(world, body="warn x; setup_user_stop; echo unreachable")
    assert (result.returncode, result.stdout.endswith("\n1 warning(s) above.\n")) == (1, True)
    assert "unreachable" not in result.stdout


def test_parse_args_leaves_a_project_as_given(world):
    out = run(world, body='setup_user_parse_args --check --project /a/b/ --github-email x@y.z; '
                          'echo "$CHECK|$UNDO|$PROJ|$GHMAIL"').stdout
    assert out == "1|0|/a/b/|x@y.z\n"
