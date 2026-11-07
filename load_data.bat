@echo off
REM ---------------------------------------------------------------------------
REM Clean the PostgreSQL database and load all CSVs from a folder.
REM Usage:  load_data.bat <datapath> [--keep]
REM   <datapath>  folder containing CSV files (searched recursively)
REM   --keep      optional: do NOT wipe the DB before loading
REM Example: load_data.bat data\raw
REM ---------------------------------------------------------------------------
setlocal

if "%~1"=="" (
    echo Usage: load_data.bat ^<datapath^> [--keep]
    echo Example: load_data.bat data\raw
    exit /b 1
)

if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

python -m app.data.load_csv %*
if errorlevel 1 (
    echo.
    echo Data load failed.
    exit /b 1
)

echo.
echo Data load complete.
endlocal
