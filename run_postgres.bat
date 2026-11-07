@echo off
REM ---------------------------------------------------------------------------
REM Run the official PostgreSQL 18 image from Docker Hub.
REM Config matches .env  ->  DB_URL=postgresql://user@localhost:5432/mydb
REM Trust auth is enabled so no password is needed for local development.
REM Data is persisted to .\data\pgdata so it survives container restarts.
REM ---------------------------------------------------------------------------
setlocal

set CONTAINER=conv-analytics-pg
set IMAGE=postgres:18
set PG_USER=user
set PG_DB=mydb
set PG_PORT=5432
set DATA_DIR=%~dp0data\pgdata

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker not found on PATH. Install Docker Desktop and retry.
    exit /b 1
)

REM If the container already exists, just (re)start it.
docker ps -a --format "{{.Names}}" | findstr /b /c:"%CONTAINER%" >nul 2>nul
if not errorlevel 1 (
    echo Container "%CONTAINER%" already exists. Starting it...
    docker start %CONTAINER%
    if errorlevel 1 ( echo Failed to start container & exit /b 1 )
    goto :done
)

echo Pulling %IMAGE% (first run only)...
docker pull %IMAGE%
if errorlevel 1 ( echo docker pull failed & exit /b 1 )

echo Starting PostgreSQL 18 container "%CONTAINER%"...
docker run -d ^
    --name %CONTAINER% ^
    -e POSTGRES_USER=%PG_USER% ^
    -e POSTGRES_DB=%PG_DB% ^
    -e POSTGRES_HOST_AUTH_METHOD=trust ^
    -p %PG_PORT%:5432 ^
    -v "%DATA_DIR%":/var/lib/postgresql ^
    %IMAGE%
if errorlevel 1 ( echo docker run failed & exit /b 1 )

:done
echo.
echo ============================================================
echo  PostgreSQL 18 is running.
echo    Host:     localhost
echo    Port:     %PG_PORT%
echo    Database: %PG_DB%
echo    User:     %PG_USER%  (no password, trust auth)
echo    Volume:   %DATA_DIR%
echo.
echo  Connection URL: postgresql://%PG_USER%@localhost:%PG_PORT%/%PG_DB%
echo.
echo  Stop:   docker stop %CONTAINER%
echo  Remove: docker rm -f %CONTAINER%
echo ============================================================
endlocal
