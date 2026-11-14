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
| `sync/sync-core.sh` | copies a hpcenv-core commit into a consumer's `core/`; `--check` finds drift | present |
| `sync/workflows/` | workflow templates a consumer copies once: drift check, personal-data check, scheduled sync | present |
| `sync/test_sync_core.py` | tests of `sync-core.sh` on throwaway repositories | present |
| `shell/accounts.sh` | `sbatch` and `salloc` wrappers that add the account from a variable | planned |
| `shell/github-identity.sh`, `shell/setup-user-common.sh` | shared user-setup helpers | planned |
| `lammps/lammps-gpu-selftest.sh` | LAMMPS GPU self-test | planned |

## How a consuming repository uses it

A consumer vendors hpcenv-core: it has a `core/` directory at its top level that is an exact
copy of one hpcenv-core commit (`git archive` of it), and `core/CORE_COMMIT` holding that
commit's full SHA. Nothing is edited in `core/` there: a change goes to hpcenv-core by pull
request and reaches the consumer by the next sync.

**Adopting.** From a clone of hpcenv-core, sync the consumer once, then commit:

```
sync/sync-core.sh -C <consumer> main
git -C <consumer> add core
git -C <consumer> commit -m "core: vendor hpcenv-core"
```

Then, from the consumer's top level, copy the three workflow templates into
`.github/workflows/` (workflows cannot run from `core/`) and commit them; the copies are the
consumer's own:

```
mkdir -p .github/workflows
cp core/sync/workflows/*.yml .github/workflows/
```

**Syncing.** From the consumer's top level (or with `-C <dir>`):

```
core/sync/sync-core.sh <ref>       # branch, tag or full commit SHA of hpcenv-core
core/sync/sync-core.sh --check     # exit 1, naming the paths, if core/ differs from CORE_COMMIT
```

The script fetches `<ref>` anonymously over HTTPS from `$HPCENV_CORE_URL` (default
`https://github.com/pzeiger/hpcenv-core.git`), replaces `core/` and writes `core/CORE_COMMIT`.
It stages and commits nothing; review the diff and commit. It refuses to run while `core/`
has staged, unstaged or untracked changes. `--check` compares file contents, not modes.

**Workflows** (`sync/workflows/`):

| Template | Runs | Does |
|---|---|---|
| `core-drift.yml` | pull requests, pushes to `main` | `core/sync/sync-core.sh --check`: red when `core/` differs from `CORE_COMMIT` |
| `personal-data.yml` | pull requests, pushes to `main` | `python3 core/checks/personal_data.py` (the nested `personal-data-allow.txt` in `core/` applies below `core/`) |
| `core-sync.yml` | weekly, by hand | syncs to hpcenv-core `main`; when that changed `core/`, force-pushes the branch `core-sync` and opens or updates one pull request; when `core/` is current again, closes a stale one |

`core-sync.yml` needs the setting "Allow GitHub Actions to create and approve pull requests"
(Settings > Actions > General). A pull request that `GITHUB_TOKEN` opens starts no workflow,
so the job starts `core-drift` and `personal-data` on the `core-sync` branch itself
(`workflow_dispatch` is the one event `GITHUB_TOKEN` may trigger) and their results appear on
the pull request. GitHub disables scheduled workflows after 60 days without repository
activity; start `core-sync` by hand from the Actions tab then. A consumer's own `pull_request` workflows stay unstarted until someone
pushes to the branch or closes and reopens the pull request.

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
