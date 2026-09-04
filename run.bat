@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the local Python environment...
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
for /f "delims=" %%G in ('".venv\Scripts\python.exe" -m discord_overlay.backend') do set "OCR_BACKEND=%%G"
if not defined OCR_BACKEND set "OCR_BACKEND=cpu"
set "INSTALLED_BACKEND="
if exist ".venv\.backend" set /p "INSTALLED_BACKEND="<".venv\.backend"
if /i "%INSTALLED_BACKEND%"=="%OCR_BACKEND%" goto :ready
echo Detected OCR backend: %OCR_BACKEND%
echo Installing dependencies and the matching ONNX Runtime...
".venv\Scripts\python.exe" -m pip uninstall -y onnxruntime onnxruntime-gpu onnxruntime-directml >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
".venv\Scripts\python.exe" -m pip install -r "requirements-%OCR_BACKEND%.txt" || goto :error
echo %OCR_BACKEND%> ".venv\.backend"
:ready
".venv\Scripts\python.exe" main.py
exit /b %errorlevel%
:error
echo.
echo Setup failed. See the error above. Python 3.12 (64-bit) from python.org is required.
pause
exit /b 1
