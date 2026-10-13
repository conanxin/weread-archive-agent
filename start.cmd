@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel%==0 (set "PYTHON=py -3") else (set "PYTHON=python")
echo ===== WeRead Archive Agent =====
%PYTHON% wereadlab.py doctor
if not exist ".local\session\weread.cookies.txt" (
  echo.
  echo First run: scan QR in browser. Install Playwright if prompted.
  %PYTHON% wereadlab.py login
)
echo.
echo Open an actual book in https://weread.qq.com/ and click Read.
echo Copy its full browser address (not the example text from README).
set /p "URL=Paste real WeRead /web/reader/ URL: "
if "%URL%"=="" exit /b 1
set /p "FULL=Export full book? Y/N [N]: "
if /i "%FULL%"=="Y" (set "SCOPE=--full") else (set "SCOPE=--sample 2")
%PYTHON% wereadlab.py export "%URL%" %SCOPE% --format epub --format pdf --format md --json
echo.
pause