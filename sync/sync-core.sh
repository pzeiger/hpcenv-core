#!/usr/bin/env bash
# Vendor hpcenv-core into a consuming repository, or check that the vendored copy is intact.
#
#   sync-core.sh [-C DIR] REF     replace core/ with hpcenv-core at REF
#   sync-core.sh [-C DIR] --check fail if core/ differs from hpcenv-core at core/CORE_COMMIT
#
# DIR (default: the current directory) is anywhere inside the consuming repository; core/ is
# at its top level. REF is a branch, a tag or a full commit SHA of hpcenv-core, fetched
# anonymously over HTTPS from $HPCENV_CORE_URL (default: the public repository).
#
# Sync writes the exact `git archive` of the resolved commit to core/ and its full SHA to
# core/CORE_COMMIT. It stages and commits nothing: the caller reviews the diff and commits.
# It refuses to run while core/ has staged, unstaged or untracked changes, so a rerun
# follows the commit of the previous sync. Check compares core/ with `git archive` of the
# commit in core/CORE_COMMIT and names every path that differs (file modes are not compared).
# After a sync this script is core/sync/sync-core.sh in the consumer.

set -euo pipefail

die() { echo "sync-core.sh: $*" >&2; exit 1; }
usage() { echo "usage: sync-core.sh [-C DIR] REF | sync-core.sh [-C DIR] --check" >&2; exit 2; }

tmp=
main() {
    local dir=. check=0 ref=
    while [ $# -gt 0 ]; do
        case $1 in
            -C) [ $# -ge 2 ] || usage; dir=$2; shift 2 ;;
            --check) check=1; shift ;;
            -*) usage ;;
            *) [ -z "$ref" ] || usage; ref=$1; shift ;;
        esac
    done
    [ $check = 1 ] && [ -n "$ref" ] && usage
    [ $check = 1 ] || [ -n "$ref" ] || usage

    cd "$dir"
    local top
    top=$(git rev-parse --show-toplevel) || die "$dir is not in a git repository"
    cd "$top"
    [ ! -L core ] || die "core is a symbolic link; it must be a directory of this repository"
    [[ $(git ls-files --stage -- core) != 160000* ]] || die "core is a submodule; it must be a directory of this repository"

    if [ $check = 1 ]; then
        [ -f core/CORE_COMMIT ] || die "core/CORE_COMMIT is missing"
        ref=$(cat core/CORE_COMMIT)
        [[ $ref =~ ^[0-9a-f]{40}$ ]] || die "core/CORE_COMMIT does not hold a full commit SHA"
    elif [ -n "$(git status --porcelain --untracked-files=all -- core)" ]; then
        die "core/ has local changes (staged, unstaged or untracked); commit or discard them first"
    fi

    tmp=$(mktemp -d "$PWD/.core-sync.XXXXXX")
    trap 'rm -rf "$tmp"' EXIT
    export GIT_TERMINAL_PROMPT=0
    git init -q "$tmp/up"
    git -C "$tmp/up" fetch -q --depth 1 "${HPCENV_CORE_URL:-https://github.com/pzeiger/hpcenv-core.git}" "$ref" || {
        [ $check = 1 ] && die "commit $ref (core/CORE_COMMIT) is not available in hpcenv-core: its history was rewritten or force-pushed, or hpcenv-core is unreachable"
        die "cannot fetch '$ref' from hpcenv-core"
    }
    local sha
    sha=$(git -C "$tmp/up" rev-parse 'FETCH_HEAD^{commit}')
    mkdir "$tmp/new"
    git -C "$tmp/up" archive --format=tar "$sha" | tar -x -C "$tmp/new"
    printf '%s\n' "$sha" > "$tmp/new/CORE_COMMIT"

    if [ $check = 1 ]; then
        local out
        out=$(diff -rq "$tmp/new" core) || {
            echo "${out//"$tmp/new"/hpcenv-core@$sha}" >&2
            die "core/ differs from hpcenv-core at $sha"
        }
        echo "core/ matches hpcenv-core at $sha"
    else
        rm -rf core
        mv "$tmp/new" core
        echo "core/ is now hpcenv-core at $sha; review and commit"
    fi
}

# The call is followed by exit, so bash never reads on in this file after main returns,
# which matters when a sync replaces the copy of this script that is running.
main "$@"
exit 0
