@echo off
REM Internet erisimi olan bir makinede calistirin: paketleri 'wheels' klasorune indirir.
REM Sonra tum proje klasorunu (wheels dahil) hedef makineye kopyalayip kurulum.bat calistirin.
REM Iki makinede Python surumu ve isletim sistemi ayni olmali.
setlocal
cd /d "%~dp0.."
python -m pip download -r requirements.txt -d wheels || (pause & exit /b 1)
echo Paketler 'wheels' klasorune indirildi.
pause
