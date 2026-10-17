@echo off
REM Siron SQL Tracer - kurulum (bir kez calistirin)
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (echo Python bulunamadi. Python 3.9+ kurun. & pause & exit /b 1)
if not exist .venv (
  echo Sanal ortam olusturuluyor...
  python -m venv .venv || (echo Sanal ortam olusturulamadi. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
if exist wheels (
  echo Paketler yerel 'wheels' klasorunden kuruluyor (internetsiz kurulum)...
  pip install --no-index --find-links wheels -r requirements.txt || (pause & exit /b 1)
) else (
  pip install -r requirements.txt || (pause & exit /b 1)
)
if not exist config.ini (
  copy config.example.ini config.ini >nul
  echo config.ini olusturuldu. Simdi Not Defteri ile acilacak: baglanti bilgilerini girin.
  notepad config.ini
)
echo.
echo Kurulum tamam. Uygulamayi baslatmak icin baslat.bat dosyasini calistirin.
echo Sifreyi Windows Kimlik Yoneticisi'ne kaydetmek icin:  .venv\Scripts\python run.py --save-password
pause
