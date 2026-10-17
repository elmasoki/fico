@echo off
REM Siron SQL Tracer - baslat
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Once kurulum.bat calistirin. & pause & exit /b 1)
title Siron SQL Tracer
.venv\Scripts\python.exe run.py --open %*
pause
