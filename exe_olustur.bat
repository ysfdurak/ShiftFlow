@echo off
rem Windows .exe paketi olusturur: dist\ShiftFlow\ShiftFlow.exe
rem Klasoru baska bilgisayara kopyalamak yeterlidir; Python kurulumu gerekmez.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
echo Testler calistiriliyor...
.venv\Scripts\python.exe -m pytest -q || (echo TESTLER BASARISIZ - paket olusturulmadi & pause & exit /b 1)
.venv\Scripts\pyinstaller.exe --noconfirm shiftflow.spec
echo.
echo Hazir: dist\ShiftFlow\ShiftFlow.exe
pause
