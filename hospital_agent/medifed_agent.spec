# PyInstaller spec for the MediFed Hospital Agent (one-folder build). Run through build_agent.py.
# Two programs share one folder: "MediFed Hospital Agent.exe" (the window) and medifed-agent.exe (headless).
# Only what a hospital's machine needs is bundled: the agent, ml/ (node client, models, data check, training)
# and the two analytics modules the node uses (DP and explainability). Server, dashboard and database code are
# excluded explicitly.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent

hidden = (
    collect_submodules("ml")
    + collect_submodules("analytics.privacy")
    + collect_submodules("analytics.explainability")
    + collect_submodules("sklearn.impute")
    + collect_submodules("sklearn.neighbors")
    + ["keyring.backends.Windows", "keyring.backends.fail"]
)
excluded = [
    "app", "backend", "fastapi", "starlette", "uvicorn", "sqlalchemy", "psycopg", "psycopg2", "jwt", "prophet",
    "statsmodels", "cmdstanpy", "matplotlib", "IPython", "jupyter", "pytest", "experiments",
    "analytics.forecasting", "analytics.hotspot", "analytics.geospatial", "analytics.planning",
]

a = Analysis(
    [str(HERE / "run_agent.py")],
    pathex=[str(ROOT), str(HERE)],
    hiddenimports=hidden,
    excludes=excluded,
    noarchive=False,
)
pyz = PYZ(a.pure)

window = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="MediFed Hospital Agent", console=False, upx=False,
)
headless = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="medifed-agent", console=True, upx=False,
)
COLLECT(window, headless, a.binaries, a.datas, name="MediFed-Hospital-Agent", upx=False)
