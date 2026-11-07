@echo off
REM ---------------------------------------------------------------------------
REM Download retail-style datasets from Kaggle as CSV into data\raw.
REM
REM Requires Kaggle API credentials (one of):
REM   - env vars KAGGLE_USERNAME and KAGGLE_KEY, or
REM   - token file at %USERPROFILE%\.kaggle\kaggle.json
REM     (Kaggle -> Settings -> "Create New Token")
REM
REM Usage:
REM   download_data.bat                  Download the curated retail set
REM   download_data.bat --list          List curated datasets
REM   download_data.bat owner/dataset   Download a specific Kaggle dataset
REM ---------------------------------------------------------------------------
setlocal

if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

python -m app.data.download_kaggle %*
if errorlevel 1 (
    echo.
    echo Download failed. Verify your Kaggle credentials and dataset refs.
    exit /b 1
)

echo.
echo Download complete. Load it with:  load_data.bat data\raw
endlocal
