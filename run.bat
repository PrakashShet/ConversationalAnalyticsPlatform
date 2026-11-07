@echo off
setlocal
if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m app.main %*
endlocal
