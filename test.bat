@echo off
setlocal
if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat

REM Run the full test suite. Live-API tests self-skip unless GEMINI_API_KEY is set.
python -m pytest tests %*
if errorlevel 1 (
    echo.
    echo Tests failed.
    exit /b 1
)
echo.
echo All tests passed.
endlocal
