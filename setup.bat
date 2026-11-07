@echo off
setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.10+ and retry.
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo venv creation failed & exit /b 1 )
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo dependency install failed & exit /b 1 )

if not exist .env (
    copy .env.example .env >nul
    echo Created .env from template. Edit it to add your GEMINI_API_KEY.
)

echo.
echo ============================================================
echo  Setup complete.
echo  Next:
echo    1. Edit .env if needed
echo    2. (Optional) python -m app.data.seed_sample_db
echo    3. run.bat
echo ============================================================
endlocal
