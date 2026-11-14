"""Tests of accounts.sh: `sbatch` and `salloc` are run in a clean bash against stub
executables that print their arguments, one per line. Project and account values are invented."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ACCOUNTS = Path(__file__).with_name("accounts.sh")
PROJECT = "ab1"

# name: (CPU template, GPU template or None, GPU partition globs or None, CPU account,
#        GPU account, a partition that is CPU, a partition that is GPU)
CLUSTERS = {
    "single-account": ("{project}", None, None, "ab1", "ab1", "regular", "regular"),
    "cpu-gpu-glob": ("{project}-x-cpu", "{project}-x-gpu", "gpu*", "ab1-x-cpu", "ab1-x-gpu",
                     "cpu-interactive", "gpu-example"),
    "cpu-gpu-exact": ("{project}-cpu", "{project}-gpu", "gpu", "ab1-cpu", "ab1-gpu", "fat", "gpu"),
}


@pytest.fixture(params=sorted(CLUSTERS))
def cluster(request):
    return CLUSTERS[request.param]


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("sbatch", "salloc"):
        # prints its arguments, one per line
        (bindir / name).write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        (bindir / name).chmod(0o755)
    return bindir


@pytest.fixture
def run(stubs, tmp_path):
    """run(cluster, "sbatch", *args, ...) -> the arguments the stub received."""

    def _run(cluster, command, *args, project=PROJECT, env=None, cwd=None, source_twice=False,
             configure=True, stdin=None, prologue=""):
        cpu, gpu, globs, *_ = cluster
        setup = []
        if configure:
            setup += [f"HPCENV_ACCOUNT_CPU='{cpu}'"]
            if gpu:
                setup += [f"HPCENV_ACCOUNT_GPU='{gpu}'"]
            if globs:
                setup += [f"HPCENV_ACCOUNT_GPU_PARTITIONS='{globs}'"]
        if project is not None:
            setup += [f"HPCENV_ACCOUNT_PROJECT='{project}'"]
        setup += [f"source {ACCOUNTS}"] * (2 if source_twice else 1)
        script = f"set -u\n{prologue}" + "\n".join(setup) + f'\n{command} "$@"\n'
        proc = subprocess.run(
            ["bash", "--norc", "-c", script, "bash", *args], capture_output=True, text=True,
            **({"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}),
            cwd=cwd or tmp_path,
            env={"PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(tmp_path), **(env or {})},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stderr == ""
        return proc.stdout.splitlines()

    return _run


@pytest.fixture
def script(tmp_path):
    def _script(body, name="job.sbatch"):
        path = tmp_path / name
        path.write_text("#!/bin/bash\n" + body)
        return str(path)

    return _script


COMMANDS = ["sbatch", "salloc"]


@pytest.mark.parametrize("command", COMMANDS)
def test_cpu_partition_gets_cpu_account(run, cluster, command):
    assert run(cluster, command, "-p", cluster[5], "-N", "1") == ["-A", cluster[3], "-p", cluster[5], "-N", "1"]


@pytest.mark.parametrize("command", COMMANDS)
def test_no_options_get_cpu_account(run, cluster, command):
    assert run(cluster, command, "--time=1:00") == ["-A", cluster[3], "--time=1:00"]


@pytest.mark.parametrize("form", ["-p {}", "-p{}", "--partition={}", "--partition {}"])
@pytest.mark.parametrize("command", COMMANDS)
def test_gpu_partition_gets_gpu_account(run, cluster, command, form):
    args = form.format(cluster[6]).split()
    assert run(cluster, command, *args) == ["-A", cluster[4], *args]


def test_partition_list_with_a_gpu_partition_is_gpu(run, cluster):
    args = ["-p", f"{cluster[5]},{cluster[6]}"]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[4], *args]


@pytest.mark.parametrize("opts", [["--gpus", "1"], ["--gpus=1"], ["-G", "1"], ["-G1"], ["--gpus-per-node=2"],
                                  ["--gpus-per-task", "1"], ["--gres=gpu:1"], ["--gres", "gpu:2"]])
@pytest.mark.parametrize("command", COMMANDS)
def test_gpu_options_get_gpu_account(run, cluster, command, opts):
    assert run(cluster, command, "-p", cluster[5], *opts) == ["-A", cluster[4], "-p", cluster[5], *opts]


@pytest.mark.parametrize("opts", [["--gres=gpu_mem:1"], ["--gres", "license:1"], ["--gpu-bind=closest"]])
def test_other_options_are_not_gpu_requests(run, cluster, opts):
    assert run(cluster, "sbatch", *opts) == ["-A", cluster[3], *opts]


def test_gpu_request_without_a_gpu_template_uses_the_one_account(run):
    cluster = CLUSTERS["single-account"]
    assert run(cluster, "salloc", "--gpus", "1", "--constraint=gpu") == ["-A", "ab1", "--gpus", "1", "--constraint=gpu"]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("given", [["-A", "x"], ["-Ax"], ["--account=x"], ["--account", "x"]])
def test_explicit_account_passes_through(run, cluster, command, given):
    args = ["-N", "1", *given, "-p", cluster[6]]
    assert run(cluster, command, *args) == args


@pytest.mark.parametrize("command, var", [("sbatch", "SBATCH_ACCOUNT"), ("salloc", "SALLOC_ACCOUNT")])
def test_account_variable_passes_through(run, cluster, command, var):
    args = ["-p", cluster[6], "-N", "1"]
    assert run(cluster, command, *args, env={var: "x"}) == args


def test_account_variable_of_the_other_command_does_not_count(run, cluster):
    assert run(cluster, "salloc", env={"SBATCH_ACCOUNT": "x"}) == ["-A", cluster[3]]
    assert run(cluster, "sbatch", env={"SALLOC_ACCOUNT": "x"}) == ["-A", cluster[3]]


def test_empty_account_variable_does_not_count(run, cluster):
    assert run(cluster, "sbatch", env={"SBATCH_ACCOUNT": ""}) == ["-A", cluster[3]]


@pytest.mark.parametrize("project", [None, ""])
@pytest.mark.parametrize("command", COMMANDS)
def test_unset_project_passes_through(run, cluster, command, project):
    args = ["-p", cluster[6], "--gpus=1"]
    assert run(cluster, command, *args, project=project) == args


def test_unconfigured_passes_through(run, cluster):
    assert run(cluster, "sbatch", "-N", "1", configure=False) == ["-N", "1"]


def test_no_arguments(run, cluster):
    assert run(cluster, "sbatch") == ["-A", cluster[3]]


def test_arguments_with_spaces_and_globs_survive(run, cluster, tmp_path):
    (tmp_path / "file.txt").write_text("")
    args = ["--job-name", "a b", "--wrap", "echo * ?", "--comment=it's"]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[3], *args]


@pytest.mark.parametrize("gpu_line, expected", [
    ("#SBATCH --partition={gpu}", "gpu"), ("#SBATCH -p {gpu}", "gpu"), ("#SBATCH --gpus=1", "gpu"),
    ("#SBATCH --gpus-per-node=4", "gpu"), ("#SBATCH -G 1", "gpu"), ("#SBATCH --gres=gpu:1", "gpu"),
    ("#SBATCH --partition={cpu}", "cpu"), ("#SBATCH --nodes=1", "cpu"),
    ("#SBATCH   --partition={gpu}   # a trailing comment mentioning -G 4", "gpu"),
    ("#SBATCH --partition={cpu}   # --gpus=1 is a comment", "cpu"),
])
def test_script_options_choose_the_account(run, script, cluster, gpu_line, expected):
    path = script(f"#SBATCH --job-name=t\n#SBATCH --account=<project>   # <- replace\n"
                  f"{gpu_line.format(gpu=cluster[6], cpu=cluster[5])}\n#SBATCH --time=1:00:00\necho hi\n")
    assert run(cluster, "sbatch", path) == ["-A", cluster[3 if expected == "cpu" else 4], path]


def test_salloc_ignores_sbatch_lines_of_its_command(run, script, cluster):
    path = script(f"#SBATCH --partition={cluster[6]}\n#SBATCH --gpus=1\n")
    assert run(cluster, "salloc", "-N1", path) == ["-A", cluster[3], "-N1", path]


def test_script_account_line_is_not_an_explicit_account(run, script, cluster):
    path = script("#SBATCH --account=<project>\n#SBATCH --partition=" + cluster[5] + "\n")
    assert run(cluster, "sbatch", path) == ["-A", cluster[3], path]


def test_command_line_partition_overrides_the_script_partition(run, script, cluster):
    gpu_script = script(f"#SBATCH --partition={cluster[6]}\n", "gpu.sbatch")
    cpu_script = script(f"#SBATCH --partition={cluster[5]}\n", "cpu.sbatch")
    assert run(cluster, "sbatch", "-p", cluster[5], gpu_script) == ["-A", cluster[3], "-p", cluster[5], gpu_script]
    assert run(cluster, "sbatch", f"--partition={cluster[6]}", cpu_script) == [
        "-A", cluster[4], f"--partition={cluster[6]}", cpu_script]


def test_script_options_stop_at_the_first_command(run, script, cluster):
    path = script(f"#SBATCH --time=1:00:00\n\n  \necho hi\n#SBATCH --partition={cluster[6]}\n")
    assert run(cluster, "sbatch", path) == ["-A", cluster[3], path]


def test_script_without_trailing_newline(run, cluster, tmp_path):
    path = tmp_path / "bare.sbatch"
    path.write_text(f"#!/bin/bash\n#SBATCH --partition={cluster[6]}")
    assert run(cluster, "sbatch", str(path)) == ["-A", cluster[4], str(path)]


def test_script_arguments_are_not_options(run, script, cluster):
    path = script("echo hi\n")
    args = ["-N", "1", path, "-A", "x", "-p", cluster[6], "--gpus=1"]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[3], *args]


def test_option_value_that_is_a_file_is_not_the_script(run, script, cluster, tmp_path):
    (tmp_path / "out.log").write_text("")
    path = script(f"#SBATCH --partition={cluster[6]}\n")
    args = ["-o", "out.log", path]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[4], *args]


def test_script_path_with_spaces(run, script, cluster, tmp_path):
    (tmp_path / "my dir").mkdir()
    path = script(f"#SBATCH --partition={cluster[6]}\n", "my dir/my job.sbatch")
    assert run(cluster, "sbatch", "-N", "1", path) == ["-A", cluster[4], "-N", "1", path]


def test_relative_script_path(run, script, cluster, tmp_path):
    script("#SBATCH --gpus=1\n")
    assert run(cluster, "sbatch", "job.sbatch") == ["-A", cluster[4], "job.sbatch"]


def test_wrap_has_no_script(run, cluster):
    args = ["--wrap", "echo hi", "-p", cluster[6]]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[4], *args]


@pytest.mark.parametrize("opts", [
    ["--output", "out.txt"], ["--exclusive"], ["--parsable"], ["--test-only", "--requeue"],
    ["--time", "1:00", "--job-name", "a b"], ["--chdir", "out.txt"], ["--sicp"], ["--zzz-flag"],
    ["--"],
])
def test_options_before_the_script_are_skipped_with_their_values(run, script, cluster, tmp_path, opts):
    (tmp_path / "out.txt").write_text("")
    path = script(f"#SBATCH --partition={cluster[6]}\n")
    assert run(cluster, "sbatch", *opts, path) == ["-A", cluster[4], *opts, path]


def test_file_without_a_shebang_is_not_the_script(run, script, cluster, tmp_path):
    (tmp_path / "plain.txt").write_text("#SBATCH --partition=%s\n" % cluster[5])
    path = script(f"#SBATCH --partition={cluster[6]}\n")
    assert run(cluster, "sbatch", "--zzz-file", "plain.txt", path) == [
        "-A", cluster[4], "--zzz-file", "plain.txt", path]


def test_double_dash_ends_the_options_before_the_script(run, script, cluster):
    path = script(f"#SBATCH --partition={cluster[5]}\n", "cm.sh")
    args = ["--", path, "-A", "x", "-p", cluster[6]]
    assert run(cluster, "sbatch", *args) == ["-A", cluster[3], *args]


def test_script_on_stdin_is_not_read(run, cluster):
    gpu_script = f"#!/bin/bash\n#SBATCH --partition={cluster[6]}\n"
    assert run(cluster, "sbatch", "-N", "1", stdin=gpu_script) == ["-A", cluster[3], "-N", "1"]
    assert run(cluster, "sbatch", "-p", cluster[6], stdin="#!/bin/bash\n") == ["-A", cluster[4], "-p", cluster[6]]


@pytest.mark.parametrize("command", COMMANDS)
def test_open_stdin_does_not_block_a_missing_script(stubs, tmp_path, cluster, command):
    read_end, write_end = os.pipe()  # a pipe nothing writes to, like a held-open ssh session
    try:
        proc = subprocess.run(
            ["bash", "--norc", "-c", f"source {ACCOUNTS}; HPCENV_ACCOUNT_PROJECT=ab1; HPCENV_ACCOUNT_CPU='{cluster[0]}'; "
             f"{command} nonexistent.sh"],
            stdin=read_end, capture_output=True, text=True, timeout=10, cwd=tmp_path,
            env={"PATH": f"{stubs}:{os.environ['PATH']}"})
    finally:
        os.close(read_end)
        os.close(write_end)
    assert proc.stdout.splitlines() == ["-A", cluster[3], "nonexistent.sh"]


def test_aliases_of_the_same_name_do_not_break_sourcing(run, cluster):
    prologue = "shopt -s expand_aliases\nalias sbatch='echo aliased'\nalias salloc='echo aliased'\n"
    assert run(cluster, "sbatch", "-N", "1", prologue=prologue) == ["-A", cluster[3], "-N", "1"]
    assert run(cluster, "salloc", "-N", "1", prologue=prologue) == ["-A", cluster[3], "-N", "1"]


def test_sourcing_twice_adds_one_account(run, script, cluster):
    path = script(f"#SBATCH --partition={cluster[6]}\n")
    assert run(cluster, "sbatch", path, source_twice=True) == ["-A", cluster[4], path]


def test_functions_are_defined_by_sourcing_only(run, cluster):
    # no variables set at all, under set -u: sourcing and calling must not fail
    assert run(cluster, "sbatch", "-N", "1", project=None, configure=False) == ["-N", "1"]


@pytest.mark.parametrize("kind, index", [("cpu", 3), ("gpu", 4)])
def test_hpcenv_account(stubs, tmp_path, cluster, kind, index):
    cpu, gpu, globs, *_ = cluster
    env = {"HPCENV_ACCOUNT_PROJECT": PROJECT, "HPCENV_ACCOUNT_CPU": cpu, "HPCENV_ACCOUNT_GPU": gpu or ""}
    proc = subprocess.run(["bash", "--norc", "-c", f"set -u; source {ACCOUNTS}; hpcenv_account {kind}"],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"], **env})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, cluster[index] + "\n", "")


@pytest.mark.parametrize("args", [[], ["bogus"], ["CPU"]])
def test_hpcenv_account_rejects_other_kinds(args):
    env = {"HPCENV_ACCOUNT_PROJECT": "ab1", "HPCENV_ACCOUNT_CPU": "{project}"}
    proc = subprocess.run(["bash", "--norc", "-c", f"set -u; source {ACCOUNTS}; hpcenv_account \"$@\"", "bash", *args],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"], **env})
    assert (proc.returncode, proc.stdout, proc.stderr) == (2, "", "usage: hpcenv_account cpu|gpu\n")


def test_hpcenv_account_is_not_visible_to_child_processes():
    proc = subprocess.run(["bash", "--norc", "-c", f"source {ACCOUNTS}; bash --norc -c 'hpcenv_account cpu'"],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert proc.returncode == 127


@pytest.mark.parametrize("env", [{}, {"HPCENV_ACCOUNT_PROJECT": "ab1"}, {"HPCENV_ACCOUNT_CPU": "{project}"}])
def test_hpcenv_account_fails_when_unconfigured(env):
    proc = subprocess.run(["bash", "--norc", "-c", f"set -u; source {ACCOUNTS}; hpcenv_account gpu"],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"], **env})
    assert (proc.returncode, proc.stdout, proc.stderr) == (1, "", "")


# A consumer checks its own job templates with this file: HPCENV_ACCOUNT_CHECK_TABLE names a
# table whose lines are `cpu|gpu <template path>` (paths relative to the table, `#` starts a
# comment), and the cluster's HPCENV_ACCOUNT_CPU, _GPU and _GPU_PARTITIONS are in the environment
# (for example from its env.sh). Every template must get the account of the kind its line names.


def _consumer_templates(table=None):
    table = table or os.environ.get("HPCENV_ACCOUNT_CHECK_TABLE")
    if not table:
        return []
    rows = (line.split("#")[0].split(maxsplit=1) for line in Path(table).read_text().splitlines())
    return [(kind, str(Path(table).parent / name.strip())) for kind, name in filter(None, rows)]


@pytest.mark.parametrize("kind, path", _consumer_templates())
def test_consumer_template(run, kind, path):
    if "HPCENV_ACCOUNT_CPU" not in os.environ:
        pytest.fail("HPCENV_ACCOUNT_CPU is not set: export the cluster's HPCENV_ACCOUNT_* variables "
                    "(its env.sh must export them) when HPCENV_ACCOUNT_CHECK_TABLE is given")
    cpu = os.environ["HPCENV_ACCOUNT_CPU"]
    gpu = os.environ.get("HPCENV_ACCOUNT_GPU", "")
    globs = os.environ.get("HPCENV_ACCOUNT_GPU_PARTITIONS", "")
    expected = (gpu if kind == "gpu" and gpu else cpu).replace("{project}", PROJECT)
    assert run((cpu, gpu, globs), "sbatch", path) == ["-A", expected, path]


def test_template_table(tmp_path):
    cluster = CLUSTERS["cpu-gpu-glob"]
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs/cpu.sbatch").write_text(f"#!/bin/bash\n#SBATCH --partition={cluster[5]}\n")
    (tmp_path / "jobs/gpu.sbatch").write_text(f"#!/bin/bash\n#SBATCH --partition={cluster[6]}\n")
    table = tmp_path / "table.txt"
    env = {**os.environ, "HPCENV_ACCOUNT_CHECK_TABLE": str(table), "HPCENV_ACCOUNT_CPU": cluster[0],
           "HPCENV_ACCOUNT_GPU": cluster[1], "HPCENV_ACCOUNT_GPU_PARTITIONS": cluster[2]}

    def check(text):
        table.write_text(text)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(Path(__file__)),
                               "-k", "test_consumer_template"], capture_output=True, text=True, env=env, cwd=tmp_path)
        return proc.stdout.splitlines()[-1]

    assert "2 passed" in check("# kind  template\ncpu jobs/cpu.sbatch  # comment\n\ngpu jobs/gpu.sbatch\n")
    assert "1 failed" in check("gpu jobs/cpu.sbatch\n")
    unset = {k: v for k, v in env.items() if k != "HPCENV_ACCOUNT_CPU"}
    out = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(Path(__file__)),
                          "-k", "test_consumer_template"], capture_output=True, text=True, env=unset, cwd=tmp_path)
    assert "HPCENV_ACCOUNT_CPU is not set" in out.stdout
    assert _consumer_templates(str(table)) == [("gpu", str(tmp_path / "jobs/cpu.sbatch"))]
