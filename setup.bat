@echo off
REM ══════════════════════════════════════════════════════════════════════════
REM  Aether Fund One — Deployment Script (Windows)
REM ══════════════════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   AETHER FUND ONE — SYSTEM SETUP v3.0   ║
echo  ╚══════════════════════════════════════════╝
echo.

SET SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM ── 1. Python version check ────────────────────────────────────────────────
echo [setup] Checking Python version...
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install Python 3.12+ from https://python.org
    pause & exit /b 1
)

FOR /F "tokens=2 delims= " %%V IN ('python --version 2^>^&1') DO SET PY_VER=%%V
echo [  OK  ] Python %PY_VER%

REM ── 2. Virtual environment ─────────────────────────────────────────────────
IF NOT EXIST ".venv" (
    echo [setup] Creating virtual environment (.venv)...
    python -m venv .venv
    echo [  OK  ] Virtual environment created.
) ELSE (
    echo [  OK  ] Virtual environment already exists.
)

CALL .venv\Scripts\activate.bat

REM ── 3. Install dependencies ────────────────────────────────────────────────
echo [setup] Installing dependencies...
pip install --upgrade pip --quiet
pip install ^
    streamlit ^
    "alpaca-py>=0.26.0" ^
    "yfinance>=0.2.40" ^
    pandas ^
    plotly ^
    "opencv-python-headless>=4.10.0" ^
    "cryptography>=42.0.0" ^
    "ultralytics>=8.2.0" ^
    "onnxruntime>=1.18.0" ^
    "sentinelsat>=1.2.1" ^
    "python-dotenv>=1.0.0" ^
    "httpx>=0.27.0" ^
    "shapely>=2.0.0" ^
    "numpy>=1.26.0" ^
    "Pillow>=10.0.0" ^
    --quiet
echo [  OK  ] Dependencies installed.

REM ── 4. Generate .env file ──────────────────────────────────────────────────
IF NOT EXIST ".env" (
    echo [setup] Generating .env from .env.example...
    copy .env.example .env >nul

    REM Generate Fernet key and append to .env
    FOR /F "delims=" %%K IN ('python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"') DO SET FERNET_KEY=%%K

    REM Use PowerShell to do the in-place replacement
    powershell -Command "(Get-Content .env) -replace 'TELEMETRY_FERNET_KEY=', 'TELEMETRY_FERNET_KEY=%FERNET_KEY%' | Set-Content .env"

    echo [  OK  ] .env created with auto-generated Fernet key.
    echo [ WARN ] Edit .env to add ALPACA_API_KEY and ALPACA_SECRET_KEY before trading.
) ELSE (
    echo [  OK  ] .env already exists — skipping generation.
)

REM ── 5. Create directories ──────────────────────────────────────────────────
IF NOT EXIST "shared" mkdir shared
IF NOT EXIST "logs"   mkdir logs
echo [  OK  ] Directories: shared\ logs\ ready.

REM ── 6. Launch system ──────────────────────────────────────────────────────
echo.
echo   Orion  -^>  on_orbit_sim.py   (logs\on_orbit_sim.log)
echo   Midas  -^>  trader.py          (logs\trader.log)
echo   Health -^>  shared\system_health.log
echo   UI     -^>  http://localhost:8501
echo.

REM Launch run_system.py in a new window
start "Aether - Process Manager" /min python run_system.py

REM Wait for agents to initialise
timeout /t 3 /noisy >nul

REM Launch Streamlit in the current window
echo [setup] Launching Command Center at http://localhost:8501 ...
.venv\Scripts\streamlit.exe run dashboard\dashboard.py ^
    --server.port 8501 ^
    --server.headless true ^
    --theme.base dark ^
    --theme.backgroundColor "#0E1117" ^
    --theme.primaryColor "#00D4FF" ^
    --theme.textColor "#C9D1D9"

pause
