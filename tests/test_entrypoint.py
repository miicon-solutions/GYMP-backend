import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


@pytest.fixture
def startup(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "startup.jsonl"
    common = """
import json, os, sys
from pathlib import Path
def record(tool, **extra):
    with Path(os.environ['STARTUP_LOG']).open('a') as output:
        output.write(json.dumps({'tool': tool, 'args': sys.argv[1:], **extra}) + '\\n')
"""
    scripts = {
        "python": """
record('python', injected=os.environ.get('INJECTED_SECRET') == 'loaded')
if os.environ.get('FAIL_STEP') == sys.argv[2]:
    sys.exit(19)
""",
        "gunicorn": """
record('gunicorn', injected=os.environ.get('INJECTED_SECRET') == 'loaded')
sys.exit(int(os.environ.get('SERVER_EXIT', '0')))
""",
    }
    for name, body in scripts.items():
        executable = bin_dir / name
        executable.write_text(f"#!{sys.executable}\n{common}{body}")
        executable.chmod(0o755)

    def run(*args, **overrides):
        env = {
            "PATH": f"{bin_dir}:{os.defpath}",
            "STARTUP_LOG": str(log),
            "PORT": "",
            "GUNICORN_WORKERS": "2",
            "GUNICORN_THREADS": "4",
            "GUNICORN_TIMEOUT": "60",
            "FAIL_STEP": "",
            "SERVER_EXIT": "0",
            "INJECTED_SECRET": "",
            **overrides,
        }
        result = subprocess.run(
            [str(ENTRYPOINT), *args], env=env, capture_output=True, text=True, cwd=tmp_path
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def test_default_startup_migrates_collects_and_serves_on_8000(startup):
    result, calls = startup()
    assert result.returncode == 0, result.stderr
    assert [row["tool"] for row in calls] == ["python", "python", "gunicorn"]
    assert calls[0]["args"] == ["manage.py", "migrate", "--noinput"]
    assert calls[1]["args"] == ["manage.py", "collectstatic", "--noinput"]
    assert calls[2]["args"][:3] == ["config.wsgi:application", "--bind", "0.0.0.0:8000"]


@pytest.mark.parametrize("step,count", [("migrate", 1), ("collectstatic", 2)])
def test_failed_initialization_never_starts_server(startup, step, count):
    result, calls = startup(FAIL_STEP=step)
    assert result.returncode == 19
    assert len(calls) == count
    assert all(row["tool"] == "python" for row in calls)


def test_port_override_and_server_exit_are_preserved(startup):
    result, calls = startup(PORT="8080", SERVER_EXIT="42")
    assert result.returncode == 42
    assert "0.0.0.0:8080" in calls[-1]["args"]


@pytest.mark.parametrize("port", ["invalid", "0", "65536", "-1", "9999999999999999999"])
def test_bad_port_fails_before_migrations(startup, port):
    result, calls = startup(PORT=port)
    assert result.returncode != 0
    assert "PORT must be" in result.stderr
    assert not calls


def test_explicit_commands_keep_arguments_without_automatic_migrations(startup):
    result, calls = startup("gunicorn", "config.wsgi:application", "argument with spaces")
    assert result.returncode == 0
    assert len(calls) == 1
    assert calls[0]["args"] == ["config.wsgi:application", "argument with spaces"]
