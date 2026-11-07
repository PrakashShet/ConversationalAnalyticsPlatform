@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Build the Windows executable.
REM
REM   run_build.bat            release build (windowed)
REM   run_build.bat --debug    console build - shows startup errors on screen
REM   run_build.bat --fast     skip the dependency install step
REM
REM Full PyInstaller output goes to build\build.log. After a successful build
REM the exe is launched with --selftest, which imports every dependency and
REM writes dist\ConvAnalytics\data\logs\selftest.log. That is what turns "the
REM exe does nothing" into an actual error message.
REM ---------------------------------------------------------------------------

set "BUILD_DEBUG="
set "SKIP_DEPS="
for %%A in (%*) do (
    if /I "%%~A"=="--debug" set "BUILD_DEBUG=1"
    if /I "%%~A"=="--fast"  set "SKIP_DEPS=1"
)

if not exist .venv (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Could not activate .venv. Delete it and run setup.bat again.
    exit /b 1
)

for /f "delims=" %%V in ('python -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%V"
echo Python !PYVER!  ^|  %CD%
if defined BUILD_DEBUG echo Mode: DEBUG ^(console window, startup errors visible^)

if not defined SKIP_DEPS (
    echo Installing dependencies...
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. See the output above.
        exit /b 1
    )
    pip install "pyinstaller>=6.0"
    if errorlevel 1 (
        echo [ERROR] Could not install PyInstaller.
        exit /b 1
    )
)

REM A running instance holds a lock on dist\, which makes rmdir fail and
REM leaves a half-deleted folder that the next build then appends to.
taskkill /F /IM ConvAnalytics.exe >nul 2>&1
taskkill /F /IM QtWebEngineProcess.exe >nul 2>&1

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist dist (
    echo [ERROR] Could not delete dist\ - a file in it is still open.
    echo         Close the app, and any Explorer window showing that folder.
    exit /b 1
)

if not exist build mkdir build
set "LOG=build\build.log"

echo.
echo Running PyInstaller... ^(full output in %LOG%^)
if defined BUILD_DEBUG (set "CONV_BUILD_DEBUG=1") else (set "CONV_BUILD_DEBUG=")
pyinstaller conv_analytics.spec --noconfirm --clean --log-level=INFO > "%LOG%" 2>&1
set "PYI_RC=%ERRORLEVEL%"

if not "%PYI_RC%"=="0" (
    echo.
    echo [ERROR] PyInstaller exited with code %PYI_RC%. Last 40 lines:
    echo ------------------------------------------------------------
    powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 40"
    echo ------------------------------------------------------------
    echo Full log: %LOG%
    exit /b 1
)

if not exist "dist\ConvAnalytics\ConvAnalytics.exe" (
    echo.
    echo [ERROR] PyInstaller reported success but the exe is missing.
    echo         Check %LOG%
    exit /b 1
)

REM The intermediate bootloader has no _internal beside it; running it by
REM mistake looks exactly like "the build is broken".
if exist "build\conv_analytics\ConvAnalytics.exe" del /q "build\conv_analytics\ConvAnalytics.exe"

echo.
echo Verifying the bundle ^(--selftest^)...
pushd dist\ConvAnalytics
ConvAnalytics.exe --selftest
set "SELFTEST_RC=%ERRORLEVEL%"
popd

set "SELFTEST_LOG=dist\ConvAnalytics\data\logs\selftest.log"
if exist "%SELFTEST_LOG%" (
    echo ------------------------------------------------------------
    type "%SELFTEST_LOG%"
    echo ------------------------------------------------------------
) else (
    echo [WARN] No selftest.log was written - the exe failed before Python
    echo        started, which usually means a missing DLL. Rebuild with:
    echo            run_build.bat --debug --fast
    echo        then run dist\ConvAnalytics\ConvAnalytics.exe from a terminal
    echo        to see the loader error.
)

for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "'{0:N0}' -f ((Get-ChildItem -Recurse dist\ConvAnalytics ^| Measure-Object -Sum Length).Sum/1MB)"`) do set "SIZE=%%S"

echo.
if not "%SELFTEST_RC%"=="0" (
    echo ============================================================
    echo  BUILD COMPLETED, BUT THE SELF-TEST FAILED
    echo  The report above names the module that failed to import.
    echo ============================================================
    exit /b 1
)

echo ============================================================
echo  Build complete: dist\ConvAnalytics\ConvAnalytics.exe
echo  Bundle size: %SIZE% MB
echo.
echo  Ship the ENTIRE dist\ConvAnalytics\ folder, including
echo  _internal\. The .exe alone will not run.
echo.
echo  Do NOT run build\conv_analytics\ConvAnalytics.exe.
echo.
echo  If the app misbehaves, check:
echo    dist\ConvAnalytics\data\logs\app.log
echo    dist\ConvAnalytics\data\logs\crash.log
echo    dist\ConvAnalytics\data\logs\selftest.log
echo ============================================================
endlocal
