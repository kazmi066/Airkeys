@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
where pythonw >nul 2>&1
if errorlevel 1 goto usepython
start "" pythonw -m airkeys receive
exit /b 0
:usepython
start "AirKeys" python -m airkeys receive
exit /b 0
