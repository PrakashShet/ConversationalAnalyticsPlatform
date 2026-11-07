@echo off
REM ---------------------------------------------------------------------------
REM Download retail datasets from public URLs - NO account or API key needed.
REM Files land in data\raw\public as CSV. Stdlib only (works before setup.bat).
REM
REM Usage:
REM   download_public.bat            Download the curated public retail set
REM   download_public.bat --list     List the public sources
REM   download_public.bat name url   Download one ad-hoc CSV URL
REM ---------------------------------------------------------------------------
setlocal

REM Prefer the venv Python if present; otherwise fall back to system Python.
if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

%PY% -m app.data.download_public %*
if errorlevel 1 (
    echo.
    echo Download failed. Check your internet connection or try --list.
    exit /b 1
)

echo.
echo Done. Load it with:  load_data.bat data\raw
endlocal
