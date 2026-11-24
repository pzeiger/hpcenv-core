# Rules for every repository that vendors hpcenv-core

A consuming repository carries this file as `core/AGENTS-common.md`: its `CLAUDE.md` imports
it (`@core/AGENTS-common.md`) and its `AGENTS.md` points to it. Change it here, in
hpcenv-core, by pull request; the consumers get it at their next core sync.

## Work in a worktree; keep the clone on `main`

A clone of an environment repository is live: `env.sh` is sourced from it in every new shell,
jobs run its templates and helpers, and other sessions read it while you work. A job submitted
from the clone runs whatever the clone has checked out at that moment. So the clone stays on
`main`, clean, and is updated with `git pull --ff-only`.

Every change, and every test of a branch, happens in a git worktree of that branch:

```
git -C <clone> fetch origin
git -C <clone> worktree add <clone>/.worktrees/<branch> -b <branch> origin/main   # new branch
git -C <clone> worktree add <clone>/.worktrees/<branch> <branch>                   # existing one
```

- Write `<clone>` as an absolute path, and add `.worktrees/` to `<clone>/.git/info/exclude`
  once, so the worktrees stay out of `git status`.
- Edit, commit and push in the worktree, and submit test jobs with the worktree's own scripts
  (`<clone>/.worktrees/<branch>/...`), so the job runs the branch under test.
- To try `main`'s version of a script while a worktree is checked out elsewhere, run it from
  the clone itself once it is up to date.
- After the branch is merged, remove its worktree by its path
  (`git -C <clone> worktree remove <clone>/.worktrees/<branch>`), and only worktrees you made.
