@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel%==0 goto launch
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:launch
set "PYTHONPATH=%~dp0src"
where pythonw >nul 2>&1
if errorlevel 1 goto usepython
start "" pythonw -m airkeys receive
exit /b 0
:usepython
start "AirKeys" python -m airkeys receive
exit /b 0
