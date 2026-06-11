import threading
import queue
import re
import time
import os
from typing import Callable, Optional
from dataclasses import dataclass
import numpy as np
import logging

from .audio_capture import AudioCapture
from .transcriber import GroqTranscriber, TranscriptionResult
from .translator import Translator

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


@dataclass
class PipelineCallbacks:
    on_transcription: Optional[Callable[[TranscriptionResult], None]] = None
    on_translation: Optional[Callable[[str, str, int], None]] = None
    on_error: Optional[Callable[[str], None]] = None
    on_device_list: Optional[Callable[[list], None]] = None
    on_silence: Optional[Callable[[], None]] = None


_MAX_WORDS = 20
_MIN_WORDS = 10


def _has_sentence_end(text: str) -> bool:
    return bool(re.search(r'[.?!](?:\s|$)', text))


def _split_phrases(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    words = text.split()
    if len(words) <= _MAX_WORDS:
        return [text]
    phrases = []
    current = []
    for i, word in enumerate(words):
        current.append(word)
        is_last = i == len(words) - 1
        at_limit = len(current) >= _MAX_WORDS
        ends_sentence = bool(re.search(r'[.?!]$', word))
        if at_limit or ends_sentence or is_last:
            phrases.append(" ".join(current))
            current = []
    return [p for p in phrases if p.strip()]


def _append_new_text(buffer: str, new_text: str) -> str:
    if not buffer:
        return new_text
    if not new_text:
        return buffer

    buf_words = buffer.lower().split()
    new_words = new_text.lower().split()

    best_k = 0
    max_k = min(len(buf_words), len(new_words))
    for k in range(max_k, 0, -1):
        if buf_words[-k:] == new_words[:k]:
            best_k = k
            break

    if best_k > 0:
        remaining_words = new_text.split()[best_k:]
        if remaining_words:
            return buffer + " " + " ".join(remaining_words)
        return buffer

    return buffer + " " + new_text


class Pipeline:
    def __init__(self, models_dir: str = "models", noise_reduce: bool = True):
        self.models_dir = models_dir
        self.callbacks = PipelineCallbacks()
        self._audio = AudioCapture(chunk_ms=66, target_sample_rate=16000, noise_reduce=noise_reduce)
        self._transcriber = GroqTranscriber(
            api_key=GROQ_API_KEY,
            model="whisper-large-v3-turbo"
        )
        self._translator = Translator(model_dir=models_dir)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._audio_queue = queue.Queue(maxsize=30)
        self._last_speech_time = 0
        self._silence_threshold_sec = 10.0
        self._buffer = ""
        self._buffer_start_time = 0.0
        self._max_buffer_age_sec = 8.0
        self._phrase_queue: list[str] = []
        self._showing_until = 0.0
        self._phrase_display_sec = 3.0
        self._short_phrase_time = 0.0
        self._short_phrase_timeout = 2.0

    def set_callbacks(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.callbacks, k):
                setattr(self.callbacks, k, v)

    def initialize(self) -> bool:
        ok = True
        ok &= self._transcriber.initialize()
        ok &= self._translator.initialize()
        if not ok and self.callbacks.on_error:
            self.callbacks.on_error("Failed to initialize models")
        return ok

    def enumerate_devices(self):
        devices = self._audio.enumerate_devices()
        if self.callbacks.on_device_list:
            self.callbacks.on_device_list(devices)
        return devices

    def set_device(self, device_index: int) -> bool:
        return self._audio.set_device(device_index)

    def start(self) -> bool:
        if self._running:
            return True
        if not self._audio.is_running():
            self._audio.set_callback(self._on_audio_data)
            if not self._audio.start():
                if self.callbacks.on_error:
                    self.callbacks.on_error("Failed to start audio capture")
                return False
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        self._audio.stop()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._transcriber.reset_buffer()
        self._buffer = ""
        self._buffer_start_time = 0.0
        self._phrase_queue.clear()

    def is_running(self) -> bool:
        return self._running

    def _on_audio_data(self, data: np.ndarray):
        try:
            self._audio_queue.put_nowait(data)
        except queue.Full:
            pass

    def _send_phrase(self, phrase: str, force: bool = False):
        if not phrase.strip():
            return
        cleaned = re.sub(r'\s*[-–—]\s*$', '', phrase).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if not cleaned:
            return
        words = cleaned.split()
        if len(words) < _MIN_WORDS and not force:
            logger.info(f"Holding short phrase ({len(words)} words): '{cleaned}'")
            self._buffer = cleaned + (" " + self._buffer if self._buffer else "")
            self._buffer_start_time = time.time()
            self._short_phrase_time = time.time()
            return
        self._short_phrase_time = 0.0
        logger.info(f"Sending phrase: '{cleaned}'")
        translated = self._translator.translate(cleaned)
        logger.info(f"Translation: '{cleaned}' -> '{translated}'")
        if self.callbacks.on_translation:
            self.callbacks.on_translation(cleaned, translated, int(time.time() * 1000))

    def _process_loop(self):
        logger.info("Process loop started (Groq Whisper)")
        chunks_processed = 0
        while self._running:
            now = time.time()

            if self._phrase_queue and now >= self._showing_until:
                phrase = self._phrase_queue.pop(0)
                self._send_phrase(phrase, force=True)
                self._showing_until = now + self._phrase_display_sec

            if self._short_phrase_time > 0 and (now - self._short_phrase_time) >= self._short_phrase_timeout:
                logger.info("Short phrase timeout reached, flushing buffer")
                self._short_phrase_time = 0.0
                self._flush_buffer(force=True)

            try:
                audio_data = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                if self._buffer.strip():
                    elapsed = now - self._buffer_start_time
                    if elapsed >= self._max_buffer_age_sec:
                        self._flush_buffer(force=True)
                continue

            chunks_processed += 1
            if chunks_processed % 30 == 0:
                logger.info(f"Audio chunks: {chunks_processed}, queue: {self._audio_queue.qsize()}")

            result = self._transcriber.process(audio_data)
            if result and result.text:
                self._last_speech_time = time.time()
                text = result.text.strip()
                logger.info(f"Transcription: '{text}'")

                self._short_phrase_time = 0.0

                if self._buffer:
                    self._buffer = _append_new_text(self._buffer, text)
                else:
                    self._buffer = text
                    self._buffer_start_time = time.time()

                if _has_sentence_end(text):
                    self._flush_buffer()
                else:
                    words = self._buffer.split()
                    if len(words) >= _MAX_WORDS + 5:
                        self._flush_buffer(force=True)
            else:
                if self._last_speech_time > 0 and (now - self._last_speech_time) > self._silence_threshold_sec:
                    self._flush_buffer(force=True)
                    if self.callbacks.on_silence:
                        self.callbacks.on_silence()
                    self._last_speech_time = 0

    def _flush_buffer(self, force: bool = False):
        text = self._buffer.strip()
        if not text:
            self._buffer = ""
            self._buffer_start_time = 0.0
            return

        has_end = _has_sentence_end(text)
        if not has_end and not force:
            return

        words = text.split()
        if len(words) < _MIN_WORDS and not has_end and not force:
            logger.info(f"Holding short buffer ({len(words)} words): '{text}'")
            return

        self._buffer = ""
        self._buffer_start_time = 0.0

        phrases = _split_phrases(text)
        if not phrases:
            return

        now = time.time()
        if now >= self._showing_until:
            self._send_phrase(phrases[0], force=force)
            self._showing_until = now + self._phrase_display_sec
            self._phrase_queue.extend(phrases[1:])
        else:
            self._phrase_queue.extend(phrases)
