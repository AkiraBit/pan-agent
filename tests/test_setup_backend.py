import json
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import setup_backend


def test_healthy_venv_reuses_the_installed_git_release(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("-r requirements-runtime.txt\npytest>=7\n", encoding="utf-8")
    runtime = tmp_path / "requirements-runtime.txt"
    repo = "https://github.com/example/project.git"
    runtime.write_text(f"project @ git+{repo}@v1.0\n", encoding="utf-8")
    project = SimpleNamespace(
        read_text=lambda _: json.dumps({
            "url": repo,
            "vcs_info": {"vcs": "git", "requested_revision": "v1.0", "commit_id": "a" * 40},
        })
    )
    available = {"project": project, "pytest": SimpleNamespace(version="8.0")}

    def distribution(name):
        if name not in available:
            raise PackageNotFoundError(name)
        return available[name]

    pip_check = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(setup_backend, "distribution", distribution)
    monkeypatch.setattr(setup_backend.subprocess, "run", pip_check)
    assert setup_backend.dependencies_ready(requirements)
    assert pip_check.call_args.args[0][1:] == ["-m", "pip", "check"]

    runtime.write_text(f"project @ git+{repo}@v1.1\n", encoding="utf-8")
    assert not setup_backend.dependencies_ready(requirements)
    runtime.write_text(f"project @ git+{repo}@v1.0\n", encoding="utf-8")
    del available["pytest"]
    assert not setup_backend.dependencies_ready(requirements)
