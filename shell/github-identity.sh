# github-identity.sh: the git e-mail address for GitHub repositories.
# Sourced by a setup-user.sh script, not run. The caller defines ok and warn
# (shell/setup-user-common.sh does, with act). Functions: github_identity_valid,
# github_identity_set, github_identity_effective, github_identity_report,
# github_identity_undo. They read and write $HOME/.gitconfig-github and the
# global git config of $HOME, and the reports name the calling script as
# setup-user.sh.
# shellcheck shell=bash
#
# Commits in a repository with a github.com remote take user.email from
# ~/.gitconfig-github, which includeIf entries in the global git config pull
# in (git 2.36 or newer), one for each way of writing a github.com remote. Every other repository keeps the global
# user.email. A GitHub noreply address (<id>+<user>@users.noreply.github.com,
# shown under GitHub > Settings > Emails) keeps the personal address out of
# public commits and still counts them as contributions.

GITHUB_IDENTITY_FILE="$HOME/.gitconfig-github"
# shellcheck disable=SC2088  # the tilde is written literally into the git config
GITHUB_IDENTITY_PATH='~/.gitconfig-github'   # as written into the global config
# One glob for each way of writing a github.com remote, and beside each a
# remote of that form for the check in github_identity_effective. The globs
# match the whole address and `*` does not cross a `/`, so a well-formed
# address on another host is not matched; a malformed ssh:// one
# (ssh://git@github.com:22@other/...) is, and then gets the GitHub address.
# ssh.github.com is GitHub's SSH endpoint on port 443. Not covered: a host
# written in capitals, an https remote with a port, the retired git://
# protocol, and remote.<name>.pushurl.
GITHUB_IDENTITY_FORMS=(
    'https://github.com/**'        'https://github.com/o/r'
    'https://*@github.com/**'      'https://user@github.com/o/r'
    'git@github.com:*/**'          'git@github.com:o/r.git'
    'github.com:*/**'              'github.com:o/r.git'
    'ssh://git@github.com/**'      'ssh://git@github.com/o/r.git'
    'ssh://git@github.com:*/**'    'ssh://git@github.com:22/o/r.git'
    'ssh://github.com/**'          'ssh://github.com/o/r.git'
    'ssh://git@ssh.github.com:*/**' 'ssh://git@ssh.github.com:443/o/r.git'
)
GITHUB_IDENTITY_KEYS=()
GITHUB_IDENTITY_PROBES=()
for ((_ghid_i = 0; _ghid_i < ${#GITHUB_IDENTITY_FORMS[@]}; _ghid_i += 2)); do
    GITHUB_IDENTITY_KEYS+=("includeIf.hasconfig:remote.*.url:${GITHUB_IDENTITY_FORMS[_ghid_i]}.path")
    GITHUB_IDENTITY_PROBES+=("${GITHUB_IDENTITY_FORMS[_ghid_i + 1]}")
done
unset _ghid_i

# True for one address: something@host.tld, no whitespace.
github_identity_valid() {   # ADDRESS
    case "$1" in
        *[[:space:]]*|*@*@*) return 1 ;;
        ?*@?*.?*) return 0 ;;
        *) return 1 ;;
    esac
}

github_identity_set() {   # ADDRESS
    local key
    git config -f "$GITHUB_IDENTITY_FILE" user.email "$1"
    for key in "${GITHUB_IDENTITY_KEYS[@]}"; do
        git config --global "$key" "$GITHUB_IDENTITY_PATH"
    done
}

# git, outside any repository the calling environment may name.
github_identity_git() {
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR git "$@"
}

# The address a commit in a repository with a github.com remote would carry:
# asked of git itself, in a throwaway repository, once for each remote form, so
# that an old git, a later user.email in the global config or a half-written
# rule all show. Prints the address, or a line starting with "differs:" when
# the forms do not all give the same one.
github_identity_effective() {
    local dir url addr first="" others="" n=0
    dir=$(mktemp -d 2>/dev/null) || { git config --global --get user.email 2>/dev/null || true; return 0; }
    if github_identity_git -C "$dir" init -q --template= 2>/dev/null; then
        for url in "${GITHUB_IDENTITY_PROBES[@]}"; do
            github_identity_git -C "$dir" config remote.origin.url "$url" 2>/dev/null || true
            addr=$(github_identity_git -C "$dir" config --get user.email 2>/dev/null || true)
            if [ "$n" = 0 ]; then
                first=$addr
            elif [ "$addr" != "$first" ]; then
                others="$others, ${addr:-none} for $url"
            fi
            n=$((n + 1))
        done
    fi
    rm -rf "$dir"
    if [ -z "$others" ]; then
        echo "$first"
    else
        echo "differs: ${first:-none} for ${GITHUB_IDENTITY_PROBES[0]}$others"
    fi
}

# The overview: which address commits in GitHub repositories carry, with a
# warning when it is not a GitHub noreply address or not the one the rule names.
github_identity_report() {
    local addr rule=""
    addr=$(github_identity_effective)
    case "$addr" in
        "differs: "*)
            warn "commits in GitHub repositories carry an address that depends on how the remote is written (${addr#differs: }): the rule is incomplete, run setup-user.sh --github-email ADDRESS"
            return 0 ;;
    esac
    if [ -f "$GITHUB_IDENTITY_FILE" ]; then
        rule=$(git config -f "$GITHUB_IDENTITY_FILE" --get user.email 2>/dev/null || true)
    fi
    if [ -n "$rule" ] && [ "$rule" != "$addr" ]; then
        warn "$GITHUB_IDENTITY_PATH names $rule, but commits in GitHub repositories carry ${addr:-no address}: the rule needs git 2.36 ($(git --version 2>/dev/null)), its includeIf entries (--github-email writes them) and no user.email set after them in the global git config"
        return 0
    fi
    case "$addr" in
        "") ok "git has no e-mail address for GitHub repositories (setup-user.sh --github-email ADDRESS sets one)" ;;
        *@users.noreply.github.com) ok "commits in GitHub repositories carry $addr" ;;
        *) warn "commits in GitHub repositories carry $addr, not a GitHub noreply address: run setup-user.sh --github-email <id>+<user>@users.noreply.github.com" ;;
    esac
}

# Removes the entries, whether they name the file with a tilde or by its
# full path; ~/.gitconfig-github stays.
github_identity_undo() {
    local key value removed=0
    for key in "${GITHUB_IDENTITY_KEYS[@]}"; do
        value=$(git config --global --get "$key" 2>/dev/null || true)
        if [ "$value" = "$GITHUB_IDENTITY_PATH" ] || [ "$value" = "$GITHUB_IDENTITY_FILE" ]; then
            git config --global --unset "$key"
            removed=1
        fi
    done
    if [ "$removed" = 1 ]; then
        echo ">> removed the GitHub e-mail rule from the global git config ($GITHUB_IDENTITY_PATH is kept)"
    fi
}
