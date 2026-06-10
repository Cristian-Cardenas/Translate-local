@echo off
echo === TradNemo - Iniciando ===
echo.

echo Verificando Python...
python --version 2>nul || (
    echo Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)

echo Instalando dependencias...
python -m pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo Error instalando dependencias
    pause
    exit /b 1
)

echo.
echo Descargando modelo Whisper base.en (primera vez ~142 MB)...
python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cuda', compute_type='float16')" 2>nul || (
    echo Modelo se descargara automaticamente al iniciar
)

echo.
echo Iniciando TradNemo...
echo Presiona ESC para configuracion
echo.

python main.py

pause