"""Tests of lammps-gpu-selftest.sh with a stub `lmp` and a stub `nvidia-smi`.

The real run needs the LAMMPS binary and a GPU, so it is not exercised here. The stub
prints a thermo table whose step-0 TotEng depends on the accelerator flags, which covers
the script's parsing, comparison and exit codes."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "lammps-gpu-selftest.sh"
LMP = r'''#!/bin/bash
if [ "$1" = "-h" ]; then echo "LAMMPS (stub)"; exit 0; fi
case "$*" in
    *"-sf gpu"*) mode=GPU ;;
    *"-sf kk"*)  mode=KK ;;
    *)           mode=CPU ;;
esac
[ "$mode" = "${STUB_FAIL:-none}" ] && { echo "ERROR: stub failure"; exit 1; }
var=ENERGY_$mode
echo "Step Temp E_pair E_mol TotEng Press"
echo "0 1.44 -6.77 0 ${!var} -5.0"
echo "100 1.1 -6.5 0 ${!var} -3.0"
echo "Total wall time: 0:00:01"
'''


def run(tmp_path, gpu=True, lmp=True, **env):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if lmp:
        (bindir / "lmp").write_text(LMP)
        (bindir / "lmp").chmod(0o755)
    (bindir / "nvidia-smi").write_text("#!/bin/bash\n" + ("echo 'GPU 0: Stub'\n" if gpu else "exit 9\n"))
    (bindir / "nvidia-smi").chmod(0o755)
    base = {"ENERGY_CPU": "-2.0", "ENERGY_GPU": "-2.0", "ENERGY_KK": "-2.0"}
    # system tools only after the stubs: the host must not provide lmp or nvidia-smi
    path = f"{bindir}:/usr/bin:/bin"
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path,
                          env={"PATH": path, "TMPDIR": str(tmp_path), **base, **env})


def test_pass_when_all_backends_agree(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "step-0 TotEng = -2.0" in result.stdout
    assert "RESULT: PASS" in result.stdout
    assert "-2.000000 vs cpu -2.000000  rel=0.00e+00  [ok]" in result.stdout


def test_mismatch_beyond_the_tolerance_fails_with_1(tmp_path):
    result = run(tmp_path, ENERGY_KK="-2.5")
    assert result.returncode == 1
    assert "MISMATCH" in result.stdout and "RESULT: FAIL — GPU/CPU energy mismatch (tol=1e-2)" in result.stdout


def test_tolerance_is_taken_from_the_environment(tmp_path):
    assert run(tmp_path, ENERGY_GPU="-2.01").returncode == 0                      # rel 5e-3 < 1e-2
    result = run(tmp_path, ENERGY_GPU="-2.01", LAMMPS_GPU_SELFTEST_TOL="1e-3")
    assert result.returncode == 1 and "(tol=1e-3)" in result.stdout


@pytest.mark.parametrize("failing", ["CPU", "GPU", "KK"])
def test_a_backend_that_does_not_run_fails_with_1(tmp_path, failing):
    result = run(tmp_path, STUB_FAIL=failing)
    assert result.returncode == 1
    assert "FAILED to run:" in result.stdout and "RESULT: FAIL — a backend did not run" in result.stdout


def test_no_lmp_exits_2(tmp_path):
    result = run(tmp_path, lmp=False)
    assert result.returncode == 2 and "ERROR: lmp not on PATH" in result.stdout


def test_no_gpu_exits_2(tmp_path):
    result = run(tmp_path, gpu=False)
    assert result.returncode == 2 and "ERROR: no NVIDIA GPU visible" in result.stdout


def test_the_usage_comment_names_no_image():
    assert "apptainer exec --nv <image>.sif lammps-gpu-selftest" in SCRIPT.read_text()
