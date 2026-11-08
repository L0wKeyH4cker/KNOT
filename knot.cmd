@echo off
setlocal
cd /d "%~dp0"
set "KNOT_PY="
if exist ".venv\Scripts\python.exe" set KNOT_PY="%~dp0.venv\Scripts\python.exe"
if defined KNOT_PY goto python_found
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "KNOT_PY=python"
if defined KNOT_PY goto python_found
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "KNOT_PY=py -3"
if defined KNOT_PY goto python_found
if exist "%USERPROFILE%\miniconda3\python.exe" set KNOT_PY="%USERPROFILE%\miniconda3\python.exe"
if not defined KNOT_PY (
  echo Python 3.10+ is required. Activate your Python environment, then try again.
  exit /b 1
)
:python_found
%KNOT_PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
%KNOT_PY% knot.py %*
exit /b %errorlevel%
