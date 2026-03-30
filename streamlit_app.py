"""
streamlit_app.py — Streamlit Cloud auto-detection entry point
=============================================================
Streamlit Cloud automatically serves the file named `streamlit_app.py`
at the repo root when no Main file path is configured.

This file simply re-exports dashboard.py so that both of the following
deployment configurations work without any code duplication:

  Option A (auto-detect):  leave Main file path blank in Streamlit Cloud —
                           Streamlit Cloud will find and serve this file.

  Option B (explicit):     set Main file path to `dashboard.py` in the
                           Streamlit Cloud new-app dialog.

Either option produces an identical live dashboard.
"""

# Execute dashboard.py in the context of this module.
# All st.* calls, imports, and the refresh loop run exactly as if the user
# had typed `streamlit run dashboard.py`.
import runpy
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

runpy.run_path(str(_here / "dashboard.py"), run_name="__main__")
