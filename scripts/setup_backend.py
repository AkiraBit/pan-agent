"""Reuse a compatible development venv without contacting package sources."""

import argparse
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.request import url2pathname


ROOT = Path(__file__).resolve().parents[1]


def _requirements(path: Path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.partition(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            yield from _requirements(path.parent / line[3:].strip())
        else:
            yield line


def _installed(manifest: Path) -> bool:
    import tomllib

    from packaging.requirements import Requirement
    from packaging.version import Version

    def active(requirement):
        return requirement.marker is None or requirement.marker.evaluate({"extra": ""})

    for line in _requirements(manifest):
        if line.startswith("-e "):
            path = (manifest.parent / line[3:].strip()).resolve()
            project = tomllib.loads((path / "pyproject.toml").read_text(encoding="utf-8"))["project"]
            dist = distribution(project["name"])
            source = json.loads(dist.read_text("direct_url.json") or "{}")
            url = source.get("url", "")
            if not (source.get("dir_info", {}).get("editable") and url.startswith("file://")):
                return False
            if Path(url2pathname(url[7:])).resolve() != path or Version(dist.version) != Version(project["version"]):
                return False
            declared = set(filter(active, map(Requirement, project.get("dependencies", []))))
            installed = set(filter(active, map(Requirement, dist.requires or [])))
            if declared != installed:
                return False
            continue

        req = Requirement(line)
        if not active(req):
            continue
        if req.extras:
            return False
        dist = distribution(req.name)
        if req.url:
            # pip resolves VCS tags over the network even when the requested
            # tag is installed. PEP 610 records the origin and resolved commit.
            repository, sep, revision = req.url.removeprefix("git+").rpartition("@")
            source = json.loads(dist.read_text("direct_url.json") or "{}")
            vcs = source.get("vcs_info", {})
            if not (req.url.startswith("git+") and sep and source.get("url") == repository
                    and vcs.get("vcs") == "git" and vcs.get("requested_revision") == revision
                    and vcs.get("commit_id")):
                return False
        elif not req.specifier.contains(dist.version, prereleases=True):
            return False
    return True


def dependencies_ready(manifest: Path) -> bool:
    try:
        if not _installed(manifest):
            return False
    except (ImportError, OSError, ValueError, PackageNotFoundError, KeyError):
        # A new/incomplete venv or a requirement we cannot check is left to pip.
        return False
    return subprocess.run(
        [sys.executable, "-m", "pip", "check"], capture_output=True, check=False
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = ROOT / "requirements.txt"
    if not args.force and dependencies_ready(manifest):
        print(">>> 后端依赖已就绪，复用 .venv", flush=True)
        return 0
    print(">>> 安装后端依赖", flush=True)
    return subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(manifest)], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
