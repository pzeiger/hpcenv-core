# Rules for this repository

hpcenv-core is public from its first commit and is vendored into other repositories, so a
mistake here is published and copied.

- **Changes reach `main` by pull request only**, the maintainer's included.
- **No personal information**: no names, user names, e-mail addresses (GitHub noreply
  addresses aside), cluster accounts, allocations or project IDs, account-tied paths,
  session data (`.claude/`, transcripts) or private notes, in files and in commit messages.
  Four deliberate exceptions, all public already, are allowed by `personal-data-allow.txt`:
  the holder line of `LICENSE`, the repository's own GitHub URL, the maintainer's commit
  identity (author and committer) and the owner account in GitHub's web-merge subject
  (`Merge pull request #N from <owner>/<branch>`). The file also lists the invented example values in the
  check's tests; nothing else goes into it without a reason in the pull request.
- **No cluster-, lab- or project-specific value** (project IDs, accounts, paths, host
  names): code here takes them from a variable that the consuming repository sets.
- **Run `python3 checks/personal_data.py` before every push** (it scans the committed state, so
  commit first), and with the maintainer's
  private literal list (`--extra`) before a push of anything moved in from a lab repository.
  CI runs the tree check without the list; the list never enters this repository.
- Changes to `checks/personal_data.py` come with tests in `checks/test_personal_data.py`;
  names and ids in tests are invented.
- Content from others (scripts, images, text) goes in only with its license checked and
  named in the pull request.
