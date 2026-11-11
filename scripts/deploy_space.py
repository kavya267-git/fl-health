"""Deploy the coordinator API to a Hugging Face Space (Docker SDK).

    pip install huggingface_hub
    set HF_TOKEN=<a Hugging Face token with write access>       (PowerShell: $env:HF_TOKEN = "...")
    python scripts/deploy_space.py <hf-username>/<space-name>

Builds a staging folder with only what the server needs (backend/, ml/, analytics/, run.py, plus
deploy/hf-space/Dockerfile and its README with the Space front matter) and uploads it, replacing the Space's
files. The token is read from the environment only; it is never written to a file or printed. Settings and
secrets are set in the Space's own settings page (docs/deploy.md), never here.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["backend/app", "backend/requirements.txt", "backend/requirements-optional.txt", "ml", "analytics", "run.py"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "checkpoints", ".pytest_cache", "*.db", "*.npz")


def stage(target: Path) -> None:
    for item in INCLUDE:
        source = ROOT / item
        destination = target / item
        if source.is_dir():
            shutil.copytree(source, destination, ignore=SKIP)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name in ("Dockerfile", "README.md"):
        shutil.copy2(ROOT / "deploy" / "hf-space" / name, target / name)
    (target / ".dockerignore").write_text("**/__pycache__\n**/*.pyc\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("space", help="<hf-username>/<space-name>")
    parser.add_argument("--dry-run", action="store_true", help="Build the staging folder and list it; upload nothing")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="medifed-space-") as tmp:
        staging = Path(tmp)
        stage(staging)
        files = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
        size = sum((staging / f).stat().st_size for f in files) / 1e6
        print(f"{len(files)} files, {size:.1f} MB")
        if args.dry_run:
            for f in files:
                print("  ", f)
            return 0
        token = os.getenv("HF_TOKEN", "").strip()
        if not token:
            print("Set HF_TOKEN (a Hugging Face token with write access) in this terminal first.", file=sys.stderr)
            return 2
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
        api.upload_folder(
            repo_id=args.space,
            repo_type="space",
            folder_path=str(staging),
            commit_message="Deploy MediFed coordinator API",
            delete_patterns=["*"],
        )
        print(f"Uploaded. The Space builds now: https://huggingface.co/spaces/{args.space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
