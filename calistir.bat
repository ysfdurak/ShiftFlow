@echo off
setlocal
rem ShiftFlow Data Studio'yu kaynak koddan baslatir.
rem Ilk calistirmada sanal ortami kurar (internet gerekir), sonrakilerde dogrudan acar.
rem PowerShell'den acarken: .\calistir.bat
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

rem Kurulum yalniz basariyla biterse "kurulum_tamam" isareti yazilir; yarim kalan kurulum bir sonraki acilista tamamlanir.
if exist "%PY%" if exist ".venv\kurulum_tamam" goto calistir

echo Ilk kurulum yapiliyor, birkac dakika surebilir...
if not exist "%PY%" (
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 goto kurulum_hatasi
)
"%PY%" -c "import ssl" 2>nul
if errorlevel 1 goto ssl_hatasi
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto kurulum_hatasi
"%PY%" -c "import PySide6, pandas, openpyxl" 2>nul
if errorlevel 1 goto kurulum_hatasi
echo tamam> ".venv\kurulum_tamam"

:calistir
rem Pencere acilmadan kapanirsa sebep shiftflow.log'da (%%LOCALAPPDATA%%\ShiftFlow) yazar.
start "" .venv\Scripts\pythonw.exe -m shiftflow %*
exit /b 0

:ssl_hatasi
echo.
echo HATA: Bu Python kurulumunda SSL calismiyor; paketler indirilemez.
echo Genellikle Anaconda'nin Python'u Anaconda Prompt disinda kullanilinca olur.
echo Cozum 1: python.org'dan Python 3.12 kurun, .venv klasorunu silip bu dosyayi yeniden acin.
echo Cozum 2: Anaconda Prompt'ta su komutlari calistirin:
echo     conda create -n shiftflow python=3.12 -y
echo     conda activate shiftflow
echo     python -m pip install -r requirements.txt
echo     python -m shiftflow
pause
exit /b 1

:kurulum_hatasi
echo.
echo HATA: Kurulum tamamlanamadi. Yukaridaki mesajlara bakin (internet baglantisi, proxy, disk izni).
echo Sorun giderildikten sonra bu dosyayi yeniden acin; kurulum kaldigi yerden devam eder.
pause
exit /b 1
