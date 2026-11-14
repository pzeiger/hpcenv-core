#!/usr/bin/env bash
# lammps-gpu-selftest — verify GPU-accelerated LAMMPS on a real GPU node.
#
# The image is built in a GPU-less sandbox, so the GPU/KOKKOS-CUDA paths cannot
# be exercised at `docker build` time (the CUDA liblammps will not even load
# without the driver libcuda.so.1). This script is the runtime counterpart:
# run it inside the container ON A GPU NODE to confirm both accelerator paths
# actually run on the hardware and agree with the CPU reference.
#
#   apptainer:   apptainer exec --nv <image>.sif lammps-gpu-selftest
#   podman-hpc:  podman-hpc run --gpu <image> lammps-gpu-selftest
#   docker:      docker run --gpus all <image> lammps-gpu-selftest
#
# It runs a small Lennard-Jones melt three ways — CPU (plain), the GPU package
# (-sf gpu), and KOKKOS-CUDA (-k on g 1 -sf kk) — and checks that the step-0
# total energy from each GPU backend matches the CPU value (the initial state is
# identical across backends, so this isolates the pair-kernel result from
# chaotic trajectory divergence). Exit 0 = PASS, 1 = ran but mismatch/failure,
# 2 = cannot run (no lmp / no GPU).
# shellcheck disable=SC2164  # the cd goes into a directory mktemp -d just made
set -uo pipefail

TOL=${LAMMPS_GPU_SELFTEST_TOL:-1e-2}   # relative tolerance on step-0 TotEng
PY=$(command -v python3 || command -v python) || { echo "python not found"; exit 2; }

command -v lmp >/dev/null 2>&1 || { echo "ERROR: lmp not on PATH"; exit 2; }
if ! nvidia-smi -L >/dev/null 2>&1; then
    echo "ERROR: no NVIDIA GPU visible. Run on a GPU node and expose the device"
    echo "       (apptainer: --nv, podman-hpc: --gpu, docker: --gpus all)."
    exit 2
fi
echo ">> GPU(s):"; nvidia-smi -L
echo ">> $(lmp -h 2>/dev/null | head -1 || echo lmp)"

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT; cd "$WORK"

cat > in.lj <<'LJ'
units           lj
atom_style      atomic
lattice         fcc 0.8442
region          box block 0 16 0 16 0 16
create_box      1 box
create_atoms    1 box
mass            1 1.0
velocity        all create 1.44 87287 loop geom
pair_style      lj/cut 2.5
pair_coeff      1 1 1.0 1.0 2.5
neighbor        0.3 bin
neigh_modify    delay 0 every 20 check no
fix             1 all nve
thermo          10
run             100
LJ

# Pull the step-0 TotEng out of a LAMMPS log (locates the TotEng column from the
# thermo header, then reads the first data row).
toteng0() { "$PY" - "$1" <<'PY'
import sys
lines = open(sys.argv[1]).read().splitlines()
for i, l in enumerate(lines):
    toks = l.split()
    if toks[:1] == ['Step'] and 'TotEng' in toks:
        j = toks.index('TotEng'); n = len(toks)
        for row in lines[i+1:]:
            f = row.split()
            if len(f) == n and f[0].lstrip('-').isdigit():
                print(f[j]); sys.exit(0)
sys.exit(1)
PY
}

run_case() {   # label  cmd...
    local name="$1"; shift
    echo ">> [$name] $*"
    if "$@" -in in.lj > "log.$name" 2>&1 && grep -q "Total wall time" "log.$name"; then
        local e; if e=$(toteng0 "log.$name"); then
            echo "   step-0 TotEng = $e"; echo "$e" > "eng.$name"; return 0
        fi
        echo "   FAILED: could not parse energy"; tail -15 "log.$name"; return 1
    fi
    echo "   FAILED to run:"; tail -20 "log.$name"; return 1
}

rc=0
run_case cpu lmp                             || rc=1
run_case gpu lmp -sf gpu -pk gpu 1           || rc=1
run_case kk  lmp -k on g 1 -sf kk            || rc=1
if [ $rc -ne 0 ]; then echo "RESULT: FAIL — a backend did not run"; exit 1; fi

TOL="$TOL" "$PY" - <<'PY'
import os
ref = float(open("eng.cpu").read())
tol = float(os.environ["TOL"]); ok = True
for name in ("gpu", "kk"):
    v = float(open("eng.%s" % name).read())
    rel = abs(v - ref) / max(abs(ref), 1e-12)
    print("   %-3s %+.6f vs cpu %+.6f  rel=%.2e  [%s]"
          % (name, v, ref, rel, "ok" if rel < tol else "MISMATCH"))
    ok = ok and rel < tol
raise SystemExit(0 if ok else 1)
PY
rc=$?
if [ $rc -eq 0 ]; then
    echo "RESULT: PASS — GPU package + KOKKOS-CUDA run on the GPU and agree with CPU"
else
    echo "RESULT: FAIL — GPU/CPU energy mismatch (tol=$TOL)"
fi
exit $rc
