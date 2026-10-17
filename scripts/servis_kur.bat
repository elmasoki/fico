@echo off
REM Siron SQL Tracer'i Windows servisi olarak kurar (NSSM gerekir: https://nssm.cc)
REM Yonetici olarak calistirin. Sifreyi once 'run.py --save-password' ile servis hesabi icin kaydedin
REM veya config.ini / ORACLE_PASSWORD ortam degiskeni ile verin.
setlocal
cd /d "%~dp0.."
where nssm >nul 2>nul || (echo nssm bulunamadi. https://nssm.cc adresinden indirip PATH'e ekleyin. & pause & exit /b 1)
set APPDIR=%CD%
nssm install SironTracer "%APPDIR%\.venv\Scripts\python.exe" "%APPDIR%\run.py"
nssm set SironTracer AppDirectory "%APPDIR%"
nssm set SironTracer DisplayName "Siron SQL Tracer"
nssm set SironTracer Start SERVICE_AUTO_START
nssm set SironTracer AppStdout "%APPDIR%\data\logs\service.log"
nssm set SironTracer AppStderr "%APPDIR%\data\logs\service.log"
nssm start SironTracer
echo Servis kuruldu: http://127.0.0.1:5000
pause
