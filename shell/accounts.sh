# shell/accounts.sh: `sbatch` and `salloc` shell functions that add `-A <account>`.
#
# Source this file from a cluster's env.sh (bash), after the variables below are set. It
# defines the functions and `hpcenv_account`; it holds no cluster value. The consumer's env.sh
# passes them in by variable (they are read when a command runs):
#
#   HPCENV_ACCOUNT_PROJECT         the member's project (the value, e.g. "${SOME_PROJECT:-}");
#                                  unset or empty: sbatch and salloc run unchanged
#   HPCENV_ACCOUNT_CPU             account template for CPU jobs; `{project}` stands for the
#                                  project; unset: sbatch and salloc run unchanged
#   HPCENV_ACCOUNT_GPU             account template for GPU jobs; unset: the CPU template
#                                  serves GPU jobs too (one account per project)
#   HPCENV_ACCOUNT_GPU_PARTITIONS  space-separated globs of GPU partition names ("gpu*");
#                                  unset: no partition counts as GPU
#
# A job is a GPU job when its partition matches one of the globs or it requests GPUs
# (`-G`, `--gpus*`, `--gres=gpu[:...]`). For sbatch the script is the first argument that is a
# regular readable file whose first line starts with `#!`: sbatch rejects any other file as a
# script ("This does not look like a batch script"), so an option's value is never taken for
# it. The options before the script and the script's `#SBATCH` lines are read, and a
# `--partition` on the command line replaces the script's; the arguments after the script
# belong to it. With no such file (--wrap, a missing file) every argument is read. A script on
# standard input is not read: the account then follows the command-line options only.
# salloc reads no script; shortcut: it reads every argument, so an option of the command it
# runs (`salloc ... srun -p gpu`) counts too.
#
# `-A` is not added when the command line carries `-A` or `--account` (any form), when
# SBATCH_ACCOUNT (for sbatch) or SALLOC_ACCOUNT (for salloc) is non-empty, or when the
# project or the CPU template is unset. The real command then gets the arguments unchanged.
#
# `hpcenv_account cpu|gpu` prints the account the templates give and returns 1 when
# project or template is unset, 2 for any other argument. It is a shell function: a script
# that runs outside the shell (an srun wrapper) sources this file itself, with the
# HPCENV_ACCOUNT_* variables exported, to use it for its default account.

hpcenv_account() {
    local tpl placeholder='{project}'
    case ${1:-} in
        cpu | gpu) ;;
        *) echo "usage: hpcenv_account cpu|gpu" >&2; return 2 ;;
    esac
    [ -n "${HPCENV_ACCOUNT_PROJECT:-}" ] || return 1
    tpl=${HPCENV_ACCOUNT_CPU:-}
    if [ "$1" = gpu ] && [ -n "${HPCENV_ACCOUNT_GPU:-}" ]; then
        tpl=$HPCENV_ACCOUNT_GPU
    fi
    [ -n "$tpl" ] || return 1
    printf '%s\n' "${tpl//"$placeholder"/"$HPCENV_ACCOUNT_PROJECT"}"
}

# _hpcenv_acct_scan TOKEN...: sets _hpcenv_acct_part (last partition), _hpcenv_acct_gpu=1 (a GPU
# option) and _hpcenv_acct_has=1 (an account option). Other options are skipped, and so are
# their values, which cannot be mistaken for ours.
_hpcenv_acct_scan() {
    while [ $# -gt 0 ]; do
        case $1 in
            -A | --account) _hpcenv_acct_has=1; shift ;;
            -A* | --account=*) _hpcenv_acct_has=1 ;;
            -p | --partition) _hpcenv_acct_part=${2-}; shift ;;
            --partition=*) _hpcenv_acct_part=${1#*=} ;;
            -p*) _hpcenv_acct_part=${1#-p} ;;
            -G | --gpus) _hpcenv_acct_gpu=1; shift ;;
            -G* | --gpus*=* | --gpus-*) _hpcenv_acct_gpu=1 ;;
            --gres) case ${2-} in gpu | gpu:*) _hpcenv_acct_gpu=1 ;; esac; shift ;;
            --gres=gpu | --gres=gpu:*) _hpcenv_acct_gpu=1 ;;
        esac
        [ $# -gt 0 ] && shift
    done
    return 0
}

# _hpcenv_acct_is_script FILE: a regular readable file whose first line starts with `#!`.
_hpcenv_acct_is_script() {
    local first=''
    [ -f "$1" ] && [ -r "$1" ] || return 1
    IFS= read -r first < "$1" || [ -n "$first" ]
    [[ $first == '#!'* ]]
}

# _hpcenv_acct_script_scan: scans the `#SBATCH` lines of a batch script on standard input,
# up to its first command, ignoring trailing comments.
_hpcenv_acct_script_scan() {
    local line i
    local -a tokens=()
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in
            '#SBATCH'[[:space:]]* | '#SBATCH')
                read -ra tokens <<< "${line#'#SBATCH'}"
                for i in "${!tokens[@]}"; do
                    case ${tokens[i]} in '#'*) tokens=("${tokens[@]:0:i}"); break ;; esac
                done
                _hpcenv_acct_scan ${tokens[@]+"${tokens[@]}"}
                ;;
            '#'*) ;;
            *[![:space:]]*) break ;;
        esac
    done
}

# _hpcenv_acct_run <sbatch|salloc> ARGS...: the body of both functions.
_hpcenv_acct_run() {
    local real=$1 kind=cpu part glob arg script=''
    local -a parts=() globs=() cmdargs=()
    local _hpcenv_acct_part='' _hpcenv_acct_gpu='' _hpcenv_acct_has=''
    shift
    case $real in
        sbatch) [ -z "${SBATCH_ACCOUNT:-}" ] || { command "$real" "$@"; return; } ;;
        *) [ -z "${SALLOC_ACCOUNT:-}" ] || { command "$real" "$@"; return; } ;;
    esac
    if [ "$real" = sbatch ]; then
        for arg in "$@"; do
            if _hpcenv_acct_is_script "$arg"; then
                script=$arg
                break
            fi
            cmdargs+=("$arg")
        done
    fi
    [ -n "$script" ] || cmdargs=("$@")
    _hpcenv_acct_scan ${cmdargs[@]+"${cmdargs[@]}"}
    if [ -z "$_hpcenv_acct_has" ] && hpcenv_account cpu > /dev/null; then
        if [ -n "$script" ]; then
            part=$_hpcenv_acct_part
            _hpcenv_acct_script_scan < "$script"
            [ -z "$part" ] || _hpcenv_acct_part=$part
        fi
        IFS=, read -ra parts <<< "$_hpcenv_acct_part"
        read -ra globs <<< "${HPCENV_ACCOUNT_GPU_PARTITIONS:-}"
        for part in ${parts[@]+"${parts[@]}"}; do
            for glob in ${globs[@]+"${globs[@]}"}; do
                # shellcheck disable=SC2053  # the glob is the point
                [[ $part == $glob ]] && _hpcenv_acct_gpu=1
            done
        done
        [ -z "$_hpcenv_acct_gpu" ] || kind=gpu
        command "$real" -A "$(hpcenv_account "$kind")" "$@"
        return
    fi
    command "$real" "$@"
}

# An alias of the same name would turn the definitions below into a syntax error.
unalias sbatch salloc 2> /dev/null || true
sbatch() { _hpcenv_acct_run sbatch "$@"; }
salloc() { _hpcenv_acct_run salloc "$@"; }
