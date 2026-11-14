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
| `shell/accounts.sh` | `sbatch` and `salloc` functions that add the account from variables; `hpcenv_account` | present |
| `shell/test_accounts.py` | tests of `accounts.sh` against stub `sbatch` and `salloc` | present |
| `shell/github-identity.sh` | the git e-mail rule for GitHub repositories (`includeIf` entries, report, undo) | present |
| `shell/setup-user-common.sh` | the cluster-independent part of a cluster's `setup-user.sh`: options, `--undo`, the `~/.bashrc` block, shared checks | present |
| `shell/test_github_identity.py`, `shell/test_setup_user_common.py` | tests of the two, in a temporary `HOME` | present |
| `lammps/lammps-gpu-selftest.sh` | runtime self-test of GPU-accelerated LAMMPS in a container image | present |
| `lammps/test_lammps_gpu_selftest.py` | tests of the self-test against stub `lmp` and `nvidia-smi` | present |

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

`core-sync.yml` names hpcenv-core's public URL, the one approved exception to the no-names rule: a
consumer that runs the check with a private literal list allow-lists that URL for
`.github/workflows/core-sync.yml` in its own `personal-data-allow.txt`.

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

## Account functions

`shell/accounts.sh` (bash) is sourced from a cluster's `env.sh`. It defines `sbatch` and `salloc`
functions that add `-A <account>`, so that a member submits `sbatch template.sbatch ...` without
editing the template's `--account` line. The consumer's `env.sh` passes the cluster's rules in
by variable, and sets them before it sources the file:

| Variable | Meaning |
|---|---|
| `HPCENV_ACCOUNT_PROJECT` | the member's project, as a value; unset or empty: the commands run unchanged |
| `HPCENV_ACCOUNT_CPU` | account template for CPU jobs, `{project}` standing for the project; unset: the commands run unchanged |
| `HPCENV_ACCOUNT_GPU` | account template for GPU jobs; unset: the CPU template serves GPU jobs too |
| `HPCENV_ACCOUNT_GPU_PARTITIONS` | space-separated globs of GPU partition names; unset: no partition counts as GPU |

A cluster has either one account for every job or one account per kind; placeholders in both
cases (the suffixes and the globs are the cluster's own). `env.sh` exports the variables, which
child processes need (the consumer template check below, scripts that call `hpcenv_account`):

```bash
# One account for CPU and GPU jobs
export HPCENV_ACCOUNT_PROJECT="${MYSITE_PROJECT:-}"
export HPCENV_ACCOUNT_CPU='{project}'

# One account per kind, GPU partitions named by a glob
export HPCENV_ACCOUNT_PROJECT="${MYSITE_PROJECT:-}"
export HPCENV_ACCOUNT_CPU='{project}-cpu'
export HPCENV_ACCOUNT_GPU='{project}-gpu'
export HPCENV_ACCOUNT_GPU_PARTITIONS='gpu*'

source core/shell/accounts.sh
```

A job counts as GPU when its partition matches a glob (a comma list matches if any entry does)
or it requests GPUs (`-G`, `--gpus*`, `--gres=gpu[:...]`). For `sbatch` the script is the first
argument that is a regular readable file whose first line starts with `#!` (`sbatch` rejects any
other file as a script, so the value of an option is never taken for it). The options before
the script and the script's `#SBATCH` lines are read; a partition on the command line replaces
the script's, and the arguments after the script belong to it. With no such file (`--wrap`, a
missing file) every argument is read. A script on standard input is not read: the account then
follows the command-line options only, so pass the script as a file or give `-p` or `--gpus` on
the command line. `salloc` reads no script and every argument of its command line, including
those of the command it runs.

The commands run unchanged, with no `-A`, when the command line has `-A` or `--account` in any
form, when `SBATCH_ACCOUNT` (`sbatch`) or `SALLOC_ACCOUNT` (`salloc`) is non-empty, or when the
project or the CPU template is unset. The real binary is called with `command`, an alias of the
same name is removed, and the file is safe to source twice and under `set -u`.

`hpcenv_account cpu|gpu` prints the account the templates give (status 1 when unconfigured, 2
for another argument). It is a shell function, not exported: a script that runs outside the
shell, such as an `srun` wrapper that needs a default `ACCOUNT`, sources `core/shell/accounts.sh`
itself, with the `HPCENV_ACCOUNT_*` variables exported.

**Checking a consumer's templates.** `shell/test_accounts.py` runs the functions against stub
executables for both kinds of cluster above (`pytest shell/test_accounts.py`). A consumer runs the same file
against its own job templates: a table file lists one template per line as `cpu <path>` or
`gpu <path>` (paths relative to the table, `#` starts a comment), and the cluster's exported
`HPCENV_ACCOUNT_CPU`, `HPCENV_ACCOUNT_GPU` and `HPCENV_ACCOUNT_GPU_PARTITIONS` must be in the
environment, which sourcing its `env.sh` first provides (the test fails and names
`HPCENV_ACCOUNT_CPU` when it is missing):

```
HPCENV_ACCOUNT_CHECK_TABLE=<table> pytest core/shell/test_accounts.py -k test_consumer_template
```

Each template must then get the account of the kind its line names.

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

## User-setup helpers

A cluster's `setup-user.sh` is a one-shot, idempotent per-user setup (`--check` reports only,
`--undo` removes what it wrote, `--github-email ADDRESS` sets the commit address for GitHub
repositories). `shell/setup-user-common.sh` holds what does not depend on the cluster, as
functions the cluster's script calls after `set -euo pipefail`; the script keeps its usage text,
the project lookup, the check of its `env.sh` and the cluster's own checks. The common file
sources `shell/github-identity.sh` from its own directory. The comment block at the top of
`setup-user-common.sh` is the interface: the variables the script sets first
(`SETUP_USER_NAME`, `SETUP_USER_PROJECT_NOUN`, `RC`, `MARK`, `ENDMARK`, `ENVSH`), the variables
the functions set (`CHECK`, `UNDO`, `GHMAIL`, `PROJ`, `WARNINGS`), the output helpers (`ok`,
`warn`, `act`, `more`) and the functions. A script, with placeholders:

```bash
#!/bin/bash
# setup-user.sh: ...usage text; --help prints this block, from line 2 to the `set -euo` line
set -euo pipefail
. "<path to core>/shell/setup-user-common.sh"
SETUP_USER_NAME=<repository name>
SETUP_USER_PROJECT_NOUN="a name"
setup_user_parse_args "$@"
setup_user_validate
ENVSH=<path of the cluster's env.sh>
RC="$HOME/.bashrc"
MARK="# >>> <repository name> (<cluster>) >>>"
ENDMARK="# <<< <repository name> (<cluster>) <<<"
if [ "$UNDO" = 1 ]; then setup_user_undo; fi
setup_user_begin "<repository name> user setup: <cluster>"
# ...the cluster's project lookup; warn "..."; setup_user_stop when it fails...
# ...when $RC has no block and CHECK is 0: setup_user_add_block <VAR> "$PROJ" <cluster>
# ...setup_user_cache_dir <dir>; setup_user_check_apptainer; the cluster's checks...
setup_user_github_report
setup_user_summary
```

`shell/github-identity.sh` can also be sourced alone by a script that defines `ok` and `warn`:
`github_identity_valid ADDRESS`, `github_identity_set ADDRESS` (writes `~/.gitconfig-github` and
one `includeIf` entry per way of writing a github.com remote in the global git config),
`github_identity_effective`, `github_identity_report` and `github_identity_undo`. The rule needs
git 2.36 or newer.

## LAMMPS GPU self-test

`lammps/lammps-gpu-selftest.sh` runs a small Lennard-Jones melt on a GPU node with the CPU
path, the GPU package and KOKKOS-CUDA, and compares the step-0 total energy of each GPU backend
with the CPU value (relative tolerance `LAMMPS_GPU_SELFTEST_TOL`, default `1e-2`). Exit 0 is a
pass, 1 a failed run or a mismatch, 2 that it cannot run (no `lmp`, no GPU). A container recipe
copies it into the image as `lammps-gpu-selftest`; run it inside the image on a GPU node
(`apptainer exec --nv <image>.sif lammps-gpu-selftest`). The tests use stub `lmp` and
`nvidia-smi` binaries: the run itself needs the LAMMPS binary and a GPU.

## Licenses

Code: BSD-3-Clause, `LICENSE`. Documentation: CC BY 4.0, `docs/LICENSE`.
