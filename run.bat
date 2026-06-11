@echo off
echo === TradNemo - Iniciando ===
echo.

echo Verificando Python...
python --version 2>nul || (
    echo Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)

echo Cargando variables de entorno...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "%%a=%%b"
)

echo Instalando dependencias...
python -m pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo Error instalando dependencias
    pause
    exit /b 1
)

echo.
echo Iniciando TradNemo...
echo Presiona ESC para configuracion
echo.

python main.py

pause
