@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required.
  exit /b 1
)
"%PYTHON%" -c "import fastapi, uvicorn, sqlalchemy, jwt" >nul 2>nul
if errorlevel 1 (
  echo Install dependencies first: python -m pip install -r Backend/requirements.txt
  exit /b 1
)
set "DATABASE_URL=sqlite:///./local_demo.db"
set "ENFORCE_AUTH=true"
echo Open http://127.0.0.1:8000 in separate teacher and student tabs.
echo SIMULATION ONLY. Press Ctrl+C to stop. Data persists in local_demo.db.
"%PYTHON%" -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000 --workers 1

