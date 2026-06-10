import threading
import queue
import time
from typing import Callable, Optional
from dataclasses import dataclass
import numpy as np
import logging

from .audio_capture import AudioCapture
from .transcriber import Transcriber, TranscriptionResult
from .translator import Translator

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class PipelineCallbacks:
    on_transcription: Optional[Callable[[TranscriptionResult], None]] = None
    on_translation: Optional[Callable[[str, str, int], None]] = None
    on_error: Optional[Callable[[str], None]] = None
    on_device_list: Optional[Callable[[list], None]] = None
    on_silence: Optional[Callable[[], None]] = None


class Pipeline:
    def __init__(self, models_dir: str = "models"):
        self.models_dir = models_dir
        self.callbacks = PipelineCallbacks()
        self._audio = AudioCapture(chunk_ms=66, target_sample_rate=16000)
        self._transcriber = Transcriber(
            model_path="base.en",
            device="cuda",
            compute_type="float16"
        )
        self._translator = Translator(model_dir=models_dir)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._audio_queue = queue.Queue(maxsize=30)
        self._last_speech_time = 0
        self._silence_threshold_sec = 2.5

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

    def is_running(self) -> bool:
        return self._running

    def _on_audio_data(self, data: np.ndarray):
        try:
            self._audio_queue.put_nowait(data)
        except queue.Full:
            pass

    def _process_loop(self):
        logger.info("Process loop started")
        chunks_processed = 0
        while self._running:
            try:
                audio_data = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            chunks_processed += 1
            if chunks_processed % 30 == 0:
                logger.info(f"Audio chunks received: {chunks_processed}, queue size: {self._audio_queue.qsize()}")

            result = self._transcriber.process(audio_data)
            if result:
                logger.info(f"Transcription: text='{result.text}', lang={result.language}, conf={result.confidence:.2f}")
                if result.text:
                    self._last_speech_time = time.time()

                    if self.callbacks.on_transcription:
                        self.callbacks.on_transcription(result)

                    if result.language == "en":
                        translated = self._translator.translate(result.text)
                        logger.info(f"Translation: '{result.text}' -> '{translated}'")
                        if translated != result.text and self.callbacks.on_translation:
                            self.callbacks.on_translation(
                                result.text, translated, result.timestamp_ms
                            )
            else:
                if self._last_speech_time > 0 and (time.time() - self._last_speech_time) > self._silence_threshold_sec:
                    if self.callbacks.on_silence:
                        self.callbacks.on_silence()
                    self._last_speech_time = 0