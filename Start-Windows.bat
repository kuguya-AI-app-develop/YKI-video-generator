@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "AIGC_EXIT_CODE=%ERRORLEVEL%"
if not "%AIGC_EXIT_CODE%"=="0" (
    echo.
    if "%AIGC_EXIT_CODE%"=="3010" echo Restart Windows, then run Start-Windows.bat again.
    if not "%AIGC_EXIT_CODE%"=="3010" echo Startup failed. Read the error above.
    pause
)
exit /b %AIGC_EXIT_CODE%
