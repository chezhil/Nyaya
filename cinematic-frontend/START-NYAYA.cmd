@echo off
cd /d "%~dp0"
echo.
echo   NYAYA FINAL - Cinematic Scrolling + Connected Dashboard
echo.
echo   Open in Chrome: http://127.0.0.1:8769/index.html
echo   Keep this black window open while previewing.
echo   Use Ctrl+C here to stop the website.
echo.
npx.cmd --yes http-server dashboard -p 8769 -c-1
pause
