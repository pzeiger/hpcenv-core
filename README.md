# hpcenv-core

Shared tooling for the HPC environment repositories of a research group: the shell helpers,
scripts and checks that two or more of those repositories would otherwise carry as copies.
It holds no cluster-, lab- or project-specific value (project IDs, accounts, paths); a
consuming repository passes those in by variable.

## Layout

| Path | What | Status |
|---|---|---|
| `LICENSE` | BSD-3-Clause, covers the code | present |
| `docs/LICENSE` | CC BY 4.0, covers documentation | present |
| `README.md`, `AGENTS.md`, `CLAUDE.md` | this file; the rules for contributors and agents; `CLAUDE.md` imports `AGENTS.md` | present |
| `checks/personal_data.py` | personal-data check (tree and history) and its tests | present |
| `personal-data-allow.txt` | this repository's exceptions to that check | present |
| `.github/workflows/checks.yml` | the check and the tests on every pull request | present |
| `sync/sync-core.sh` | copies a hpcenv-core commit into a consumer's `core/` | planned |
| `shell/accounts.sh` | `sbatch` and `salloc` wrappers that add the account from a variable | planned |
| `shell/github-identity.sh`, `shell/setup-user-common.sh` | shared user-setup helpers | planned |
| `lammps/lammps-gpu-selftest.sh` | LAMMPS GPU self-test | planned |

## How a consuming repository uses it

A consumer vendors hpcenv-core: it has a `core/` directory at its top level that is an exact
copy of one hpcenv-core commit, and `core/CORE_COMMIT` naming that commit. `core/sync-core.sh
<ref>` replaces `core/` from that ref of `github.com/pzeiger/hpcenv-core`, and the change
arrives in the consumer by pull request. Nothing is edited in `core/` there: a change goes to
hpcenv-core by pull request and reaches the consumer by the next sync.

## Personal-data check

```
python3 checks/personal_data.py [--repo DIR] [--history] [--extra LIST] [--allow FILE]
```

Tree mode scans every file of the committed HEAD, `--history` every commit (diff lines,
author, committer, message, annotated tags). It finds e-mail addresses (not noreply and
reserved example addresses), NERSC project IDs, Delta, DeltaAI, NAISS, SNIC, LUMI and ACCESS
project or allocation IDs, and home, scratch and project paths with a user name in them;
`<…>` placeholders, `$USER`, `${USER}`, `*` and `~` in place of the user name pass.
`--extra` takes a private list of literals (names, user names) that never belongs in a
repository; the output names the file, line and pattern but never the matched text.
Exceptions are listed in `personal-data-allow.txt` files: each applies below its own
directory, so a vendored copy in `core/` brings its own. `python3 checks/personal_data.py
--help` and the module docstring give the details. The tests are
`checks/test_personal_data.py` (pytest).

## Licenses

Code: BSD-3-Clause, `LICENSE`. Documentation: CC BY 4.0, `docs/LICENSE`.
