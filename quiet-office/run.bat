@echo off
rem Allquiet launcher. Double-click to install what is missing and start the app.
rem Frontend always starts. Backend starts too when Python 3.10+ is installed.
rem The Python environment (.venv) and the keys (.env) live in the repository root.
setlocal
cd /d "%~dp0"
title Allquiet launcher

echo.
echo  Allquiet
echo  -----------

where node >nul 2>nul
if errorlevel 1 (
  echo  Node.js was not found. Install it from https://nodejs.org and run this again.
  goto :fail
)

if not exist "frontend\node_modules" (
  echo  Installing frontend packages, this takes a minute...
  pushd frontend
  call npm install --no-fund --no-audit
  if errorlevel 1 goto :fail
  popd
)

rem Find a real Python 3.10+. The Microsoft Store placeholder fails this check.
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)

rem Anaconda is often installed without being on PATH.
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY="%USERPROFILE%\anaconda3\python.exe""
if not defined PY if exist "%USERPROFILE%\miniconda3\python.exe" set "PY="%USERPROFILE%\miniconda3\python.exe""

if not defined PY (
  echo.
  echo  Python 3.10 or newer was not found, so only the frontend will start.
  echo  The page will show the quick estimate. To run on Allsolve, install Python
  echo  from https://www.python.org ^(tick "Add python.exe to PATH"^) and run this again.
  goto :frontend
)

if not exist "..\.venv\Scripts\python.exe" (
  echo  Creating the Python environment...
  %PY% -m venv ..\.venv
  if errorlevel 1 goto :fail
)

"..\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, pydantic_settings, allsolve" >nul 2>nul
if errorlevel 1 (
  echo  Installing backend packages, this takes a minute...
  "..\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r backend\requirements.txt
  if errorlevel 1 goto :fail
)

if not exist "..\.env" (
  copy /y "..\.env.example" "..\.env" >nul
  echo.
  echo  Created .env in the repository root. Open it and fill in QS_ACCESS_KEY and
  echo  QS_SECRET_KEY, then restart the backend window. Until then "Run on Allsolve"
  echo  stays disabled and the page shows the quick estimate.
)

echo  Starting the backend on http://localhost:8000 ...
start "Allquiet backend" /d "%~dp0backend" cmd /k ..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

:frontend
echo  Starting the frontend on http://localhost:5173 ...
start "Allquiet frontend" /d "%~dp0frontend" cmd /k npm run dev

rem Give the dev server a moment before opening the browser.
ping -n 6 127.0.0.1 >nul
start "" http://localhost:5173

echo.
echo  Running. Close the "Allquiet frontend" and "Allquiet backend" windows to stop.
ping -n 9 127.0.0.1 >nul
exit /b 0

:fail
echo.
echo  Something went wrong. The message above says what.
pause
exit /b 1
