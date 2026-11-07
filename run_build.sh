#!/usr/bin/env bash
# Build the application bundle.
#
#   ./run_build.sh            release build (windowed)
#   ./run_build.sh --debug    console build - shows startup errors
#   ./run_build.sh --fast     skip the dependency install step
#
# Runs under Git Bash / MSYS on Windows and natively on Linux and macOS. The
# virtualenv layout differs between them (Scripts/ vs bin/), so it is detected
# rather than assumed.
#
# Full PyInstaller output goes to build/build.log. After a successful build the
# executable is run with --selftest, which imports every dependency and writes
# data/logs/selftest.log — that is what turns "the exe does nothing" into a
# readable error.

set -euo pipefail
cd "$(dirname "$0")"

BUILD_DEBUG=""
SKIP_DEPS=""
for arg in "$@"; do
    case "$arg" in
        --debug) BUILD_DEBUG=1 ;;
        --fast)  SKIP_DEPS=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

die() { echo "[ERROR] $*" >&2; exit 1; }

[[ -d .venv ]] || die "Virtual environment not found. Run setup.bat (Windows) or create .venv first."

# Windows venvs put executables in Scripts/, POSIX ones in bin/.
if [[ -x .venv/Scripts/python.exe ]]; then
    VENV_BIN=".venv/Scripts"; EXE_SUFFIX=".exe"
elif [[ -x .venv/bin/python ]]; then
    VENV_BIN=".venv/bin"; EXE_SUFFIX=""
else
    die "No python found in .venv/Scripts or .venv/bin."
fi
PY="$VENV_BIN/python$EXE_SUFFIX"

echo "Python $("$PY" -c 'import sys;print(sys.version.split()[0])')  |  $PWD"
[[ -n "$BUILD_DEBUG" ]] && echo "Mode: DEBUG (console build, startup errors visible)"

if [[ -z "$SKIP_DEPS" ]]; then
    echo "Installing dependencies..."
    "$PY" -m pip install --upgrade pip >/dev/null
    "$PY" -m pip install -r requirements.txt || die "Dependency install failed."
    "$PY" -m pip install "pyinstaller>=6.0" || die "Could not install PyInstaller."
fi

# A running instance keeps a lock on dist/ under Windows.
if command -v taskkill >/dev/null 2>&1; then
    taskkill //F //IM ConvAnalytics.exe >/dev/null 2>&1 || true
    taskkill //F //IM QtWebEngineProcess.exe >/dev/null 2>&1 || true
fi

rm -rf build dist
[[ -d dist ]] && die "Could not delete dist/ - something still has a file open."
mkdir -p build
LOG="build/build.log"

echo
echo "Running PyInstaller... (full output in $LOG)"
if [[ -n "$BUILD_DEBUG" ]]; then export CONV_BUILD_DEBUG=1; else unset CONV_BUILD_DEBUG || true; fi

if ! "$PY" -m PyInstaller conv_analytics.spec --noconfirm --clean --log-level=INFO > "$LOG" 2>&1; then
    echo
    echo "[ERROR] PyInstaller failed. Last 40 lines:"
    echo "------------------------------------------------------------"
    tail -n 40 "$LOG"
    echo "------------------------------------------------------------"
    echo "Full log: $LOG"
    exit 1
fi

APP="dist/ConvAnalytics/ConvAnalytics$EXE_SUFFIX"
[[ -f "$APP" ]] || die "PyInstaller reported success but $APP is missing. Check $LOG"

# The intermediate bootloader has no _internal beside it; running it by mistake
# looks exactly like a broken build.
rm -f "build/conv_analytics/ConvAnalytics$EXE_SUFFIX"

echo
echo "Verifying the bundle (--selftest)..."
SELFTEST_RC=0
( cd dist/ConvAnalytics && "./ConvAnalytics$EXE_SUFFIX" --selftest ) || SELFTEST_RC=$?

SELFTEST_LOG="dist/ConvAnalytics/data/logs/selftest.log"
if [[ -f "$SELFTEST_LOG" ]]; then
    echo "------------------------------------------------------------"
    cat "$SELFTEST_LOG"
    echo "------------------------------------------------------------"
else
    echo "[WARN] No selftest.log was written - the executable failed before"
    echo "       Python started, which usually means a missing shared library."
    echo "       Rebuild with: ./run_build.sh --debug --fast"
fi

SIZE=$(du -sm dist/ConvAnalytics | cut -f1)

echo
if [[ "$SELFTEST_RC" -ne 0 ]]; then
    echo "============================================================"
    echo " BUILD COMPLETED, BUT THE SELF-TEST FAILED"
    echo " The report above names the module that failed to import."
    echo "============================================================"
    exit 1
fi

cat <<EOF
============================================================
 Build complete: $APP
 Bundle size: ${SIZE} MB

 Ship the ENTIRE dist/ConvAnalytics/ folder, including
 _internal/. The executable alone will not run.

 Do NOT run build/conv_analytics/ConvAnalytics$EXE_SUFFIX.

 If the app misbehaves, check:
   dist/ConvAnalytics/data/logs/app.log
   dist/ConvAnalytics/data/logs/crash.log
   dist/ConvAnalytics/data/logs/selftest.log
============================================================
EOF
