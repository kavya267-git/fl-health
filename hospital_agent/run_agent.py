"""Entry point of the MediFed Hospital Agent (also the PyInstaller entry).

From a source checkout:  python hospital_agent/run_agent.py [--server ... --token ... --data ...]
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Running from source: the agent uses the repository's ml/ and analytics/ packages.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from medifed_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
