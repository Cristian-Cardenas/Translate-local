import time
import io
import wave
import numpy as np
import requests
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

HALLUCINATIONS = {
    "thank you",
}


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    start_time: float
    end_time: float
    audio_duration: float
    realtime_factor: float


class GroqTranscriber:
    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo"):
        self.api_key = api_key
        self.model = model
        self._min_samples = 16000 * 5
        self._buffer = np.array([], dtype=np.float32)
        self._last_text = ""
        self._last_time = 0.0
        self._api_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        self._online = True
        self._local_model = None
        self._local_model_name = "base.en"
        self._using_local = False

    def _is_hallucination(self, text: str) -> bool:
        cleaned = text.strip().lower().rstrip(".")
        return cleaned in HALLUCINATIONS

    def initialize(self) -> bool:
        if self._online:
            logger.info(f"Groq API ready. Model: {self.model}")
            return True
        return self._init_local()

    def _init_local(self) -> bool:
        try:
            from faster_whisper import WhisperModel
            import os
            models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models")
            os.makedirs(models_dir, exist_ok=True)
            logger.info(f"Loading local model: {self._local_model_name}")
            self._local_model = WhisperModel(self._local_model_name, device="cpu", compute_type="int8", download_root=models_dir)
            self._using_local = True
            logger.info("Local model loaded")
            return True
        except Exception as e:
            logger.error(f"Failed to load local model: {e}")
            return False

    def _np_to_wav_bytes(self, audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        audio_int16 = (audio * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()

    def _has_speech(self, audio: np.ndarray) -> bool:
        rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
        if rms < 0.005:
            logger.debug(f"Audio too quiet (RMS={rms:.6f}), skipping")
            return False
        return True

    def process(self, audio_chunk: np.ndarray) -> Optional[TranscriptionResult]:
        self._buffer = np.concatenate([self._buffer, audio_chunk])
        if len(self._buffer) < self._min_samples:
            return None
        audio_to_send = self._buffer.copy()
        self._buffer = np.array([], dtype=np.float32)
        if not self._has_speech(audio_to_send):
            return None
        if self._online:
            return self._transcribe_online(audio_to_send)
        else:
            return self._transcribe_local(audio_to_send)

    def _transcribe_online(self, audio: np.ndarray) -> Optional[TranscriptionResult]:
        start = time.time()
        wav_bytes = self._np_to_wav_bytes(audio)
        try:
            resp = requests.post(
                self._api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")},
                data={"model": self.model, "temperature": 0.0, "response_format": "verbose_json"},
                timeout=15
            )
            if resp.status_code == 401:
                logger.warning("Groq API key invalid. Switching to local model.")
                self._online = False
                self._init_local()
                return self._transcribe_local(audio)
            if resp.status_code in (429, 402):
                logger.warning(f"Groq rate limited/quota ({resp.status_code}). Switching to local model.")
                self._online = False
                self._init_local()
                return self._transcribe_local(audio)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "").strip()
            lang = data.get("language", "en")
            duration = data.get("duration", len(audio) / 16000)
            elapsed = time.time() - start
            rtf = elapsed / duration if duration > 0 else 99
            logger.info(f"Groq transcription: '{text}'")
            if self._is_hallucination(text):
                logger.info(f"Filtered hallucination: '{text}'")
                return None
            if text and not (text == self._last_text and (time.time() - self._last_time) < 2.0):
                self._last_text = text
                self._last_time = time.time()
                return TranscriptionResult(text=text, language=lang, confidence=0.9, start_time=0, end_time=duration, audio_duration=duration, realtime_factor=rtf)
        except requests.exceptions.RequestException as e:
            logger.error(f"Groq request failed: {e}")
            self._online = False
            self._init_local()
            return self._transcribe_local(audio)
        return None

    def _transcribe_local(self, audio: np.ndarray) -> Optional[TranscriptionResult]:
        if self._local_model is None:
            return None
        start = time.time()
        segments, info = self._local_model.transcribe(audio, beam_size=1, language="en", condition_on_previous_text=False, initial_prompt="Fashion, clothing, bra, top, shorts.")
        text_parts = []
        for seg in segments:
            text_parts.append(seg.text.strip())
        text = " ".join(text_parts).strip()
        elapsed = time.time() - start
        duration = len(audio) / 16000
        rtf = elapsed / duration if duration > 0 else 99
        logger.info(f"Local transcription ({rtf:.2f}x RTF): '{text}'")
        if self._is_hallucination(text):
            logger.info(f"Filtered hallucination: '{text}'")
            return None
        if text and not (text == self._last_text and (time.time() - self._last_time) < 2.0):
            self._last_text = text
            self._last_time = time.time()
            return TranscriptionResult(text=text, language=info.language, confidence=info.language_probability, start_time=0, end_time=duration, audio_duration=duration, realtime_factor=rtf)
        return None

    def reset_buffer(self):
        self._buffer = np.array([], dtype=np.float32)
