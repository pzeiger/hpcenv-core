# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Scan a git repository for personal data that must not reach a public repository.

Run it from anywhere in a repository (or pass --repo) before every push:

    python3 checks/personal_data.py [--repo DIR] [--history] [--extra LIST] [--allow FILE]

Tree mode (default) scans every file of the committed HEAD, from the repository top level
whatever the current directory: uncommitted and untracked changes are not seen, so commit
first. Symlinks are scanned as their target string, binary files as UTF-8 or else latin-1 text, UTF-16
files with a byte-order mark as UTF-16. --history scans every commit instead: the added and
deleted diff lines (merges against their first parent), author and committer name and
address, message, and the tagger and message of annotated tags. Exit status: 0 clean, 1 at
least one hit, 2 usage or internal error.

The output may land in a public CI log, so a hit names only where it is and which pattern
fired, never the matched text or its line:

    tree mode     <path>:<line>: <pattern>      (<path>:? for a binary file)
    --history     <commit, 12 hex digits> <path | author | committer | message | tag> <pattern>

Generic patterns (the code holds no names):
    email          any address except GitHub noreply addresses (the Actions bot among them),
                   `noreply@github.com`, `noreply@anthropic.com` (the commit attribution
                   trailer) and addresses at the reserved example domains (example.com,
                   .org, .net and their subdomains; *.example, *.invalid, *.test)
    nersc-project  `m` and 4 digits, also with a `_g` suffix
    delta-account  4 lowercase letters, then `-delta-cpu`, `-delta-gpu` or `-dtai-gh`
    naiss-project  `naiss` or `snic` in any case, optionally a space, a year 20xx, then
                   two numbers separated by `-` or `/` (`NAISS 2025/<n>-<n>`)
    lumi-project   `project_46` and 7 digits
    access-allocation  3 capital letters and 6 digits
    path           /home, /Users, /u, /users, /global/cfs/cdirs, /global/homes/<x>,
                   /pscratch/sd/<x>, /cfs/klemming/home/<x> and /cfs/klemming/scratch/<x>
                   followed by a user segment; a segment that starts with `<` (`<user>`),
                   `$` (`$USER`, `${USER}`), `*` or `~` is a placeholder and passes
Paths that need the cluster's own layout to be told from ordinary ones
(`/projects/<account>/<user>`, `/work/<user>`, `/scratch/<...>`) are left to --extra.

Not scanned: compressed containers (zip, docx, gz) are not unpacked, UTF-16 without a
byte-order mark is decoded byte-wise and so not matched, and the tagger of a `mergetag`
header inside a merge commit is not parsed.

--extra LIST is a private file of literals, one per line, `#` starts a comment line. Each
literal is matched case-insensitively as a substring, after Unicode NFC normalisation of
both sides (so a user name inside a path or an identifier still hits), and reported as
`extra:<line number in LIST>`. A literal shorter than 3 characters is a usage error: it
would match inside nearly every file.

Allow-lists hold the exceptions, one per line, three tab-separated fields:

    <path glob> TAB <pattern name> TAB <text>

Every tracked file named `personal-data-allow.txt` is one; its globs are relative to its own
directory and apply only below it, so a vendored copy of this repository in `core/` brings
its own. --allow FILE adds one more (globs relative to the repository top level). The
metadata locations `author`, `committer`, `message` and `tag` match only globs of the
top-level allow-lists (the tracked root `personal-data-allow.txt` and --allow), not nested
ones. A hit is suppressed when its path matches the glob (`*` also crosses `/`), its
pattern name equals the entry's (`extra` covers every `extra:<n>`), and the hit's matched
span lies inside an occurrence of <text> in its line. For a generic pattern <text> is
normally the matched text itself; for an `extra` literal it can be a longer context (a URL,
a copyright line, a commit identity), so the list need not name the literal alone and allows
it nowhere else.

The allow-lists are scanned like any file, in every version in --history. A hit in one is
suppressed only when it lies inside the <text> field of an entry of a current allow-list
with the same pattern name; a comment is scanned like any text.
"""

import argparse
import fnmatch
import posixpath
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ALLOW_NAME = "personal-data-allow.txt"
NOREPLY_SUFFIX = "@users.noreply.github.com"
EXEMPT_EMAILS = ("noreply@anthropic.com", "noreply@github.com")
# RFC 2606 and 6761 reserved domains: no real person has an address there.
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")
EXAMPLE_SUFFIXES = tuple("." + d for d in EXAMPLE_DOMAINS) + (".example", ".invalid", ".test")
_SEG = r"[^/\\\s'\"`,;:)\]]*[^/\\\s'\"`,;:)\].]"


def _personal_email(m):
    address = m.group().lower()
    domain = address.rpartition("@")[2]
    return not (address.endswith(NOREPLY_SUFFIX) or address in EXEMPT_EMAILS
                or domain in EXAMPLE_DOMAINS or domain.endswith(EXAMPLE_SUFFIXES))


# name: (regex, keep(match) -> bool, or None to keep every match)
PATTERNS = {
    "email": (
        re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
        ),
        _personal_email,
    ),
    # `_` may follow (the GPU account suffix), a letter or digit may not (`m12345`);
    # neither may precede, so ids inside identifiers and random strings do not hit.
    "nersc-project": (re.compile(r"(?<![A-Za-z0-9_])m[0-9]{4}(?![A-Za-z0-9])"), None),
    "delta-account": (
        re.compile(r"(?<![A-Za-z0-9])[a-z]{4}-(?:delta-(?:cpu|gpu)|dtai-gh)(?![A-Za-z0-9])"),
        None,
    ),
    "naiss-project": (re.compile(r"(?i:naiss|snic) ?20[0-9]{2}[-/][0-9]+[-/][0-9]+"), None),
    "lumi-project": (re.compile(r"(?<![A-Za-z0-9_])project_46[0-9]{7}(?![0-9])"), None),
    "access-allocation": (re.compile(r"(?<![A-Za-z0-9_])[A-Z]{3}[0-9]{6}(?![A-Za-z0-9_])"), None),
    # The prefix may follow `file:/` or `/` (`file://` or `//` before `/home/<user>`), not a path
    # component (`a/home/<user>`, `$HOME/home/<user>`, a URL path).
    "path": (
        re.compile(
            r"(?<![\w.~}$])(?<![\w.~}$]/)"
            r"(?:/home|/Users|/u|/users|/global/cfs/cdirs"
            r"|(?:/global/homes|/pscratch/sd|/cfs/klemming/home|/cfs/klemming/scratch)/[^/\s]+)"
            r"/(?P<user>" + _SEG + ")"
        ),
        lambda m: not m.group("user").startswith(("<", "$", "*", "~")),
    ),
}


class UsageError(Exception):
    pass


def nfc(text):
    return unicodedata.normalize("NFC", text)


def text_lines(text):
    return [line.removesuffix("\r") for line in text.split("\n")]


def decode_list(data, path, what):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"cannot read {what} file {path}: {exc}")


def read_file(path, what):
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read {what} file {path}: {exc}")
    return decode_list(data, path, what)


def list_lines(text):
    """Yield (line number, line) of a list file, without blank and comment lines."""
    for n, line in enumerate(text_lines(text), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            yield n, line


def load_extra(path):
    extra = []
    for n, line in list_lines(read_file(path, "extra")):
        literal = nfc(line.strip())
        if len(literal) < 3:
            raise UsageError(f"{path}:{n}: literal shorter than 3 characters")
        extra.append((n, re.compile(re.escape(literal), re.IGNORECASE)))
    return extra


class Allow:
    """The entries (directory, glob, pattern name, text) of all allow-lists."""

    def __init__(self):
        self.entries = []
        self.current = set()

    def add(self, text, where, directory):
        for n, line in list_lines(text):
            fields = nfc(line).split("\t", 2)
            if len(fields) != 3 or not all(fields):
                raise UsageError(f"{where}:{n}: expected <path glob> TAB <pattern name> TAB <text>")
            if fields[1] not in (*PATTERNS, "extra"):
                raise UsageError(f"{where}:{n}: unknown pattern name {fields[1]!r}")
            self.entries.append((directory, *fields))
            self.current.add(tuple(fields))

    def allows(self, loc, line, name, span):
        base = name.split(":")[0]
        if posixpath.basename(loc) == ALLOW_NAME:
            fields = tuple(line.split("\t", 2))
            return (fields in self.current and fields[1] == base
                    and span[0] >= len(fields[0]) + len(fields[1]) + 2)
        for directory, glob, pname, text in self.entries:
            if directory and not loc.startswith(directory + "/"):
                continue
            rel = loc[len(directory) + 1:] if directory else loc
            if pname != base or not fnmatch.fnmatchcase(rel, glob):
                continue
            i = line.find(text)
            while i >= 0:
                if i <= span[0] and span[1] <= i + len(text):
                    return True
                i = line.find(text, i + 1)
        return False


def scan_line(loc, line, extra, allow):
    """Return the pattern names that hit `line` and are not allowed at `loc`."""
    line = nfc(line)
    found = [(name, m.span()) for name, (rx, keep) in PATTERNS.items()
             for m in rx.finditer(line) if keep is None or keep(m)]
    found += [(f"extra:{n}", m.span()) for n, rx in extra for m in rx.finditer(line)]
    names = []
    for name, span in found:
        if name not in names and not allow.allows(loc, line, name, span):
            names.append(name)
    return names


def git(repo, *args, stdin=None):
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=off", *args]
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UsageError(f"`git {args[0]}` failed in {repo}: {exc}")


def cat_file(repo, shas):
    """Return the raw content of each object in `shas` (git cat-file --batch)."""
    out = git(repo, "cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in shas).encode())
    contents, pos = [], 0
    for _ in shas:
        end = out.index(b"\n", pos)
        size = int(out[pos:end].split()[2])
        contents.append(out[end + 1:end + 1 + size])
        pos = end + size + 2
    return contents


def head_files(repo):
    """Return (path, sha) of every blob (symlinks included) of HEAD, from the top level."""
    files = []
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            if meta.split()[1] == b"blob":
                files.append((path.decode("utf-8", "replace"), meta.split()[2].decode()))
    return files


def decode_blob(data):
    """Return (text, binary). UTF-16 with a byte-order mark is read as UTF-16, other content
    as UTF-8 or else latin-1; a NUL in the first 8 kB marks a binary file."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace"), False
    binary = b"\0" in data[:8192]
    try:
        return data.decode("utf-8"), binary
    except UnicodeDecodeError:
        return data.decode("latin-1"), binary


def tree_hits(repo, files, extra, allow):
    for (path, _), data in zip(files, cat_file(repo, [sha for _, sha in files])):
        text, binary = decode_blob(data)
        if binary:
            for name in sorted({n for line in text_lines(text) for n in scan_line(path, line, extra, allow)}):
                yield f"{path}:?: {name}"
            continue
        for n, line in enumerate(text_lines(text), 1):
            for name in scan_line(path, line, extra, allow):
                yield f"{path}:{n}: {name}"


def history_hits(repo, extra, allow):
    seen = set()

    def hits(sha, loc, line):
        for name in scan_line(loc, line, extra, allow):
            if (sha, loc, name) not in seen:
                seen.add((sha, loc, name))
                yield f"{sha[:12]} {loc} {name}"

    # Commit and tag objects are read raw, length-prefixed, so no byte in a message can
    # break the parsing.
    commits = git(repo, "rev-list", "--all").decode().split()
    refs = git(repo, "for-each-ref", "--format=%(objecttype) %(objectname)", "refs/tags").decode().split("\n")
    tags = [line.split()[1] for line in refs if line.startswith("tag ")]
    for sha, raw in zip(commits + tags, cat_file(repo, commits + tags)):
        header, _, message = raw.decode("utf-8", "replace").partition("\n\n")
        for line in header.split("\n"):
            m = re.match(r"(author|committer|tagger) (.*) \d+ [+-]\d{4}$", line)
            if m:
                yield from hits(sha, "tag" if m[1] == "tagger" else m[1], m[2])
        for line in text_lines(message):
            yield from hits(sha, "tag" if sha in tags else "message", line)

    # -U0 diffs: after `diff --git` come header lines up to the first `@@`; in a hunk every
    # line starting with + or - is content (a content line `+++ x` is not a header).
    diffs = git(repo, "log", "--all", "-p", "-U0", "--text", "--no-color", "--no-ext-diff", "--no-renames",
                "--diff-merges=first-parent", "--format=%x1e%H").decode("utf-8", "replace")
    sha = path = state = None
    for line in diffs.split("\n"):
        if line.startswith("\x1e"):
            sha, path, state = line[1:], None, None
        elif line.startswith("diff --git "):
            path, state = None, "header"
        elif state == "header":
            if line.startswith("--- ") and line != "--- /dev/null":
                path = line[4:].removeprefix("a/").split("\t")[0]
            elif line.startswith("+++ ") and line != "+++ /dev/null":
                path = line[4:].removeprefix("b/").split("\t")[0]
            elif line.startswith("@@"):
                state = "hunk"
        elif state == "hunk" and line[:1] in ("+", "-"):
            yield from hits(sha, path, line[1:])


def run(args):
    extra = load_extra(args.extra) if args.extra else []
    files = head_files(args.repo)
    allow = Allow()
    allow_files = [(p, s) for p, s in files if posixpath.basename(p) == ALLOW_NAME]
    for (path, _), data in zip(allow_files, cat_file(args.repo, [s for _, s in allow_files])):
        allow.add(decode_list(data, path, "allow-list"), path, posixpath.dirname(path))
    if args.allow:
        allow.add(read_file(args.allow, "allow-list"), args.allow, "")
    if args.history:
        return list(history_hits(args.repo, extra, allow))
    return list(tree_hits(args.repo, files, extra, allow))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan a git repository for personal data.")
    parser.add_argument("--repo", default=".", help="repository to scan (default: current directory)")
    parser.add_argument("--history", action="store_true", help="scan every commit instead of the tree")
    parser.add_argument("--extra", help="private file of literals, one per line")
    parser.add_argument("--allow", help="allow-list in addition to the tracked personal-data-allow.txt files")
    args = parser.parse_args(argv)
    try:
        hits = run(args)
    except UsageError as exc:
        print(f"personal_data: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # the message could hold scanned text: name the type only
        print(f"personal_data: internal error ({type(exc).__name__})", file=sys.stderr)
        return 2
    for hit in hits:
        print(hit)
    print(f"personal_data: {len(hits)} hit(s)", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
