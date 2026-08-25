@echo off
REM Serves the webapp at http://localhost:8080 so Web Bluetooth works.
cd /d "%~dp0webapp"
where python >nul 2>nul
if %errorlevel%==0 (
  echo Starting server: http://localhost:8080  (Ctrl+C to stop)
  start "" http://localhost:8080/index.html
  python -m http.server 8080
  goto :eof
)
where py >nul 2>nul
if %errorlevel%==0 (
  echo Starting server: http://localhost:8080  (Ctrl+C to stop)
  start "" http://localhost:8080/index.html
  py -m http.server 8080
  goto :eof
)
where npx >nul 2>nul
if %errorlevel%==0 (
  echo Starting server: http://localhost:8080  (Ctrl+C to stop)
  start "" http://localhost:8080/index.html
  npx --yes http-server -p 8080 -c-1
  goto :eof
)
echo Neither Python nor Node.js was found. Install one of them,
echo or open index.html directly ^(real BLE will use simulation mode^).
pause
