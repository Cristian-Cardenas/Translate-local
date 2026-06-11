# TradNemo - Agente de Desarrollo

## Descripción
Aplicación de escritorio Windows para traducción en tiempo real de audio del inglés al español.
Captura audio del sistema (lo que sale por los speakers), lo reduce de ruido (noisereduce),
lo transcribe con Groq Whisper API (sistema híbrido con fallback a modelo local si se agota 
el free tier), lo traduce con Google Translate, y muestra los subtítulos en un overlay transparente.

## Arquitectura

```
main.py                    # Orquestador: inicializa componentes, maneja callbacks, flujo UI
src/
  core/
    audio_capture.py        # Captura de audio loopback con pyaudiowpatch (WASAPI)
    transcriber.py          # Transcripción: Groq Whisper + fallback a faster-whisper local
    translator.py           # Traducción online con Google Translate (deep-translator)
    pipeline.py             # Hilo de procesamiento: audio → transcripción → traducción
  ui/
    overlay.py              # Interfaz: panel de configuración + overlay transparente
models/                     # Modelos descargados (solo si Groq falla)
```

## Flujo de Datos
1. `AudioCapture` captura audio loopback del sistema a 16kHz mono
2. Los chunks de audio (~66ms cada uno) se encolan en un `queue.Queue(maxsize=30)`
3. `Pipeline._process_loop` (hilo separado) toma chunks del queue
4. `GroqTranscriber` acumula audio hasta tener 5+ segundos
5. **Sistema híbrido**: intenta Groq API primero; si falla, cambia a modelo local
6. Groq Whisper Large V3 Turbo transcribe con alta precisión (7.7% WER)
7. Pipeline acumula texto hasta tener una oración completa (termina en `.`, `?`, `!`)
8. La oración completa se divide en frases cortas (10-20 palabras)
9. Cada frase se traduce independentmente con Google Translate EN→ES
10. Cada frase se muestra en el overlay por 3 segundos, luego se reemplaza con la siguiente

## Sistema Híbrido de Transcripción

### Modo Primario: Groq Whisper API
- **API**: Groq Whisper (https://api.groq.com/openai/v1/audio/transcriptions)
- Modelo: `whisper-large-v3-turbo` (809M parámetros, ~7.7% WER)
- Velocidad: 216x tiempo real (sub-segundo)
- **Gratis**: rate limits generosos en free tier
- Requiere: API key de Groq (gratis en console.groq.com)

### Fallback: Modelo Local (faster-whisper)
- Se activa automáticamente si:
  - API key de Groq inválida (error 401)
  - Rate limit excedido (error 429)
  - Cuota agotada (error 402)
  - Error de conexión a internet
- Modelo: `base.en` (~150MB, se descarga la primera vez)
- Velocidad: ~0.5x tiempo real en CPU (más lento)
- Precisión: ~15% WER (menor que Groq)
- No requiere internet ni API key

### Transición Transparente
- El usuario no nota el cambio; la app sigue funcionando
- Se loggea el cambio de modo
- Si Groq se recupera, se mantiene en local (evita flickering)

## Componentes Clave

### AudioCapture (`src/core/audio_capture.py`)
- Usa `pyaudiowpatch` (variante de PyAudio con soporte WASAPI loopback)
- Auto-detecta el dispositivo de salida por defecto y selecciona su loopback correspondiente
- Convierte stereo a mono y resamplea a 16kHz para Whisper
- **Reducción de ruido**: usa `noisereduce` (spectral gating) para filtrar música/ruido externo
  - Modo non-stationary: se adapta a ruido variable (música, fondo)
  - `prop_decrease=0.8`: reduce ruido al 80% (ajustable)
  - Se ejecuta en cada chunk antes de enviar al transcriptor
- Callback asíncrono por cada chunk de audio

### GroqTranscriber (`src/core/transcriber.py`)
- **Clase híbrida**: Groq API + fallback a faster-whisper
- Buffer: acumula audio 5 segundos antes de procesar
- Convierte numpy array a WAV antes de enviar a Groq
- **Filtro de alucinaciones**: detecta y descarta texto fantasma ("Thank you.", "Thanks for watching", etc.)
- **Verificación de energía**: descarta audio silencioso (RMS < 0.01) antes de transcribir
- Detección automática de errores de API
- Transición transparente entre modos

### Translator (`src/core/translator.py`)
- Usa Google Translate vía `deep-translator` (gratis, sin API key)
- Requiere conexión a internet
- Thread-safe con lock

### Pipeline (`src/core/pipeline.py`)
- Hilo daemon que procesa audio continuamente
- **Acumulación inteligente**: concatena transcripciones solapadas con deduplicación
- **Detección de oraciones completas**: espera a que el texto termine en `.`, `?`, `!`
- **División en frases**: splits oraciones largas en fragmentos de 10-20 palabras
- **Cola de frases**: las frases se muestran secuencialmente, cada una por 3 segundos
- **Timeout de frases cortas**: frases <10 palabras esperan 3 segundos antes de mostrar
  - Si llega más texto dentro de 3s → se combina
  - Si pasan 3s sin nuevo texto → se muestra igual
- Callbacks: `on_transcription`, `on_translation`, `on_error`, `on_device_list`, `on_silence`
- Detección de silencio: si no hay habla por 10 segundos, llama `on_silence`
- Timeout: si el buffer acumula texto por 8 segundos sin terminador, lo procesa igual

### Overlay (`src/ui/overlay.py`)
- Tkinter puro, sin dependencias externas
- Dos estados:
  1. **Panel de configuración**: selector de dispositivo de audio + botón "Iniciar captura"
  2. **Overlay transparente**: muestra subtítulos sobre otras ventanas
- Características del overlay:
  - Siempre encima (topmost)
  - Transparente al mouse (click-through) por defecto
  - Ctrl+Alt+T o Escape: alterna modo interactivo (permite mover/redimensionar)
  - Arrastrar desde centro: mueve la ventana
  - Arrastrar desde esquinas/bordes: redimensiona
  - Font responsive: tamaño de fuente escala proporcional al tamaño de la ventana
  - Cada traducción reemplaza la anterior (sin acumulación)
  - Auto-hide después de 45 segundos sin actividad

## Dependencias
```
requests               # HTTP requests para Groq API
deep-translator        # Traducción online (Google Translate, gratis)
pyaudiowpatch          # Captura de audio WASAPI loopback
numpy>=2.0             # Procesamiento de audio
psutil>=5.9            # Utilidades del sistema
faster-whisper         # Modelo local (fallback si Groq falla)
noisereduce            # Reducción de ruido (spectral gating)
```

## API Keys Requeridas
- **Groq**: API key para Whisper transcription (gratis en console.groq.com)
- **Google Translate**: No requiere API key (uso gratuito vía deep-translator)
- **Fallback local**: No requiere API key

## Ejecución
- **Doble clic en `run.bat`**: instala dependencias + inicia la app
- **Doble clic en `TradNemo.lnk`**: inicia sin ventana de consola
- **Doble clic en `run.vbs`**: inicia sin ventana de consola
- **`python main.py`**: inicia directamente (asumiendo dependencias instaladas)

## Configuración
- Modelo Groq: `whisper-large-v3-turbo` (cambiar en `pipeline.py` constante `GROQ_API_KEY`)
- Modelo local fallback: `base.en` (cambiar en `transcriber.py` constante `_local_model_name`)
- Tiempo de visualización por frase: 3 segundos (cambiar en `pipeline.py` constante `_phrase_display_sec`)
- Máximo de palabras por frase: 20 (cambiar en `pipeline.py` constante `_MAX_WORDS`)
- Mínimo de palabras por frase: 10 (cambiar en `pipeline.py` constante `_MIN_WORDS`)
- Timeout de frases cortas: 2 segundos (cambiar en `pipeline.py` constante `_short_phrase_timeout`)
- Auto-hide: 45 segundos (cambiar en `overlay.py` método `_start_auto_hide_timer`)
- Buffer de audio: 5 segundos (cambiar en `transcriber.py` constante `_min_samples`)
- Reducción de ruido: habilitada por defecto (cambiar en `main.py` o `pipeline.py`)

## Notas Técnicas
- El audio loopback solo funciona en Windows con WASAPI (Windows Vista+)
- Groq free tier: rate limits generosos, sin costo
- Si Groq falla, la app cambia automáticamente a modelo local (sin intervención del usuario)
- El modelo local es más lento pero funciona sin internet
- El overlay usa `ctypes.windll.user32` para manipular estilos de ventana Win32
- Python 3.14 probado; debe funcionar con 3.10+
