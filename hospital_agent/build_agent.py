"""Build the Windows agent: a one-folder PyInstaller build, zipped as MediFed-Hospital-Agent-Windows.zip.

    python hospital_agent/build_agent.py --server https://<your-api>     # in a venv with hospital_agent/requirements.txt

The --server value is pre-filled in the agent's window (the operator can change it). The build writes into
hospital_agent/dist/ and hospital_agent/build/ (git-ignored).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
ZIP_NAME = "MediFed-Hospital-Agent-Windows.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="http://localhost:8000", help="API address pre-filled in the window")
    args = parser.parse_args()

    defaults = HERE / "medifed_agent" / "defaults.py"
    original = defaults.read_text(encoding="utf-8")
    defaults.write_text(
        '"""Build-time defaults. build_agent.py rewrites DEFAULT_SERVER with the deployed API address."""\n\n'
        f'DEFAULT_SERVER = "{args.server.rstrip("/")}"\n',
        encoding="utf-8",
    )
    started = time.time()
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", str(DIST), "--workpath", str(HERE / "build"), str(HERE / "medifed_agent.spec")],
            check=True,
        )
    finally:
        defaults.write_text(original, encoding="utf-8")
    folder = DIST / "MediFed-Hospital-Agent"
    (folder / "README.txt").write_text(
        "MediFed Hospital Agent\n======================\n\n"
        "Double-click 'MediFed Hospital Agent.exe'. Paste the node token from your hospital's 'My hospital' page,\n"
        "choose your data folder (or 'Use sample data (SIMULATED)' to try it), click 'Check data', then 'Connect'.\n\n"
        "Headless: medifed-agent.exe --server <address> --token <token> --data <folder>\n\n"
        "Your records stay on this computer. Only model updates, record counts and summary metrics are sent.\n",
        encoding="utf-8",
    )
    archive = DIST / ZIP_NAME
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, Path("MediFed-Hospital-Agent") / path.relative_to(folder))
    size = archive.stat().st_size / 1e6
    unpacked = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6
    print(f"Built {archive} ({size:.0f} MB zipped, {unpacked:.0f} MB unpacked) in {time.time() - started:.0f} s")
    shutil.rmtree(HERE / "build", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
