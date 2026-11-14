# setup-user-common.sh: the part of a cluster's per-user setup script (setup-user.sh)
# that does not depend on the cluster.
# Sourced by that script after `set -euo pipefail`, not run. The script keeps what is
# the cluster's own: its usage text, the project lookup, the check of the
# environment file (env.sh) and the cluster's checks. This file sources
# github-identity.sh, which sits beside it.
# shellcheck shell=bash
# shellcheck disable=SC2034  # PROJ, CHECK, UNDO, GHMAIL are read by the calling script
#
# Names this file defines or resets in the calling shell. A script that sources it must not
# use them for anything else: the variables below, the functions `ok`, `warn`, `act`, `more`
# (`more` shadows /usr/bin/more inside the script) and `setup_user_*`, `SETUP_USER_COMMON_DIR`,
# and the names github-identity.sh defines (`github_identity_*`, `GITHUB_IDENTITY_*`).
#
# Variables the calling script sets, before the first call that reads them:
#   SETUP_USER_PROJECT_NOUN   before setup_user_parse_args: what --project takes, as in
#                             "--project needs <noun>", e.g. "a name"
#   SETUP_USER_NAME           before setup_user_undo: name of the repository, e.g. "my-env", used in
#                             messages and in the backup file name ($RC.$SETUP_USER_NAME-backup)
#   RC                        before setup_user_undo and setup_user_add_block: the shell startup
#                             file, normally "$HOME/.bashrc"
#   MARK, ENDMARK             before setup_user_undo and setup_user_add_block: the two lines that
#                             enclose the block in $RC
#   ENVSH                     before setup_user_add_block: path of the environment file the block
#                             sources
# Variables the functions set or reset, for the script to read:
#   CHECK (0|1)  --check: report only, change nothing (reset to 0 by setup_user_parse_args)
#   UNDO (0|1)   --undo: remove the block and the GitHub e-mail rule (reset to 0 likewise)
#   GHMAIL       --github-email ADDRESS, or "" (reset likewise)
#   PROJ         --project VALUE exactly as given, or "" (reset likewise); the script strips a
#                trailing slash itself when its project is a directory
#   WARNINGS     number of warnings so far; set to 0 when this file is sourced
#
# Output helpers, which the scripts and github-identity.sh call:
#   ok TEXT   warn TEXT (counted)   act TEXT   more TEXT (continues a warning, not counted)
#
# Functions, in the order a script calls them:
#   setup_user_parse_args "$@"       reads --check, --undo, --github-email ADDRESS, --project VALUE
#                                    and -h/--help (prints the script's leading comment block, from
#                                    its second line to the line before `set -euo`); exits 1 on
#                                    anything else
#   setup_user_validate              exits 1 for an invalid --github-email or --check with --undo
#   setup_user_undo                  --undo: removes the GitHub e-mail rule and the block from $RC
#                                    (backup first), then exits 0; exits 1 and changes nothing when
#                                    the markers are not one start line above one end line
#   setup_user_begin TITLE           prints TITLE and the --check note; applies --github-email
#                                    (writes the rule, unless --check) before anything else can stop
#                                    the script
#   setup_user_add_block VAR VALUE CLUSTER
#                                    appends the block to $RC: `export VAR=VALUE` and a line that
#                                    sources $ENVSH when it is readable
#   setup_user_cache_dir DIR         ok/create/warn for the apptainer cache directory DIR
#   setup_user_check_apptainer       ok/warn for apptainer on PATH
#   setup_user_github_report         the address commits in GitHub repositories carry
#   setup_user_stop                  prints the warning count and exits 1 (the script's early stop)
#   setup_user_summary               prints "All good." or the warning count

SETUP_USER_COMMON_DIR=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=github-identity.sh
. "$SETUP_USER_COMMON_DIR/github-identity.sh"

WARNINGS=0
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
act()  { printf '  did   %s\n' "$*"; }
more() { printf '        %s\n' "$*"; }

setup_user_parse_args() {
    GHMAIL="" CHECK=0 UNDO=0 PROJ=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --check)   CHECK=1; shift ;;
            --github-email) { [ $# -ge 2 ] && [ -n "$2" ]; } || { echo "--github-email needs an address" >&2; exit 1; }
                       GHMAIL=$2; shift 2 ;;
            --undo)    UNDO=1;  shift ;;
            --project) [ $# -ge 2 ] || { echo "--project needs $SETUP_USER_PROJECT_NOUN" >&2; exit 1; }
                       PROJ=$2; shift 2 ;;
            -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; $d'; exit 0 ;;
            *) echo "unknown option: $1 (try --help)" >&2; exit 1 ;;
        esac
    done
}

setup_user_validate() {
    if [ -n "$GHMAIL" ] && ! github_identity_valid "$GHMAIL"; then
        echo "not an e-mail address: $GHMAIL" >&2
        exit 1
    fi
    if [ "$CHECK" = 1 ] && [ "$UNDO" = 1 ]; then
        echo "--check and --undo exclude each other" >&2
        exit 1
    fi
}

setup_user_undo() {
    local starts ends
    github_identity_undo
    if [ -f "$RC" ] && grep -qxF "$MARK" "$RC"; then
        # One start marker with one end marker below it; with anything else
        # the range below would cut to the end of the file.
        starts=$(grep -nxF "$MARK" "$RC" | cut -d: -f1 || true)
        ends=$(grep -nxF "$ENDMARK" "$RC" | cut -d: -f1 || true)
        case "$starts:$ends" in
            *[!0-9:]*|:*|*:) starts=0; ends=0 ;;
        esac
        if [ "$starts" -ge "$ends" ]; then
            echo "$RC: the $SETUP_USER_NAME markers are not one start line followed by one" >&2
            echo "  end line; nothing changed. Remove the block by hand." >&2
            exit 1
        fi
        cp -p "$RC" "$RC.$SETUP_USER_NAME-backup"
        sed -i --follow-symlinks "/^${MARK}\$/,/^${ENDMARK}\$/d" "$RC"
        # ...and the blank lines at the end of the file, which removes the one
        # written before the block when the block was the last thing added.
        sed -i --follow-symlinks -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$RC"
        echo ">> removed the $SETUP_USER_NAME block from $RC (backup: $RC.$SETUP_USER_NAME-backup)"
        echo "   Open a new shell; the current one still has env.sh applied."
    else
        echo ">> no $SETUP_USER_NAME block found in $RC"
    fi
    exit 0
}

setup_user_begin() {   # TITLE
    echo "$1"
    if [ "$CHECK" = 1 ]; then echo "(--check: reporting only, nothing will be changed)"; fi
    echo
    # The address commits in GitHub repositories carry. Set here, before anything
    # below can stop the script: it does not depend on the cluster or the project.
    if [ -n "$GHMAIL" ] && [ "$CHECK" = 0 ]; then
        github_identity_set "$GHMAIL"
        act "GitHub repositories now commit as $GHMAIL (~/.gitconfig-github)"
        echo
    fi
}

setup_user_add_block() {   # VAR VALUE CLUSTER
    {
        echo ""
        echo "$MARK"
        echo "# Added by setup-user.sh. Safe to source anywhere: env.sh is silent,"
        echo "# idempotent, and does nothing off $3."
        echo "export $1=$2"
        echo "if [ -r \"$ENVSH\" ]; then . \"$ENVSH\"; fi"
        echo "$ENDMARK"
    } >> "$RC"
    act "added the block to $RC"
    act "run '. $RC' or open a new shell to pick it up now"
}

setup_user_cache_dir() {   # DIR
    if [ -d "$1" ]; then
        ok "apptainer cache directory exists: $1"
    elif [ "$CHECK" = 1 ]; then
        warn "no apptainer cache directory yet: $1 (run without --check to create it)"
    elif mkdir -p "$1"; then
        act "created $1"
    else
        warn "could not create $1"
    fi
}

setup_user_check_apptainer() {
    if command -v apptainer >/dev/null 2>&1; then
        ok "apptainer is on PATH"
    else
        warn "apptainer is not on PATH (are you on a login node?)"
    fi
}

setup_user_github_report() {
    if [ -n "$GHMAIL" ] && [ "$CHECK" = 1 ]; then
        warn "--github-email is not applied with --check"
    fi
    github_identity_report
}

setup_user_stop() {
    echo
    echo "$WARNINGS warning(s) above."
    exit 1
}

setup_user_summary() {
    echo
    if [ "$WARNINGS" -eq 0 ]; then
        echo "All good."
    else
        echo "$WARNINGS warning(s) above."
    fi
}
