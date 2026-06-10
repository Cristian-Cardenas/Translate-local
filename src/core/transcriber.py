from faster_whisper import WhisperModel
import numpy as np
import threading
import time
from typing import Optional, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    timestamp_ms: int


class Transcriber:
    def __init__(self, model_path: str = "base.en", device: str = "cuda", compute_type: str = "float16"):
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._buffer = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._min_samples = 16000 * 3
        self._max_samples = 16000 * 30
        self._overlap_samples = 16000 * 1
        self._last_text = ""

    def initialize(self) -> bool:
        try:
            self._model = WhisperModel(
                self.model_path,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=0,
                num_workers=1,
            )
            return True
        except Exception as e:
            print(f"Transcriber init error: {e}")
            return False

    def process(self, audio_chunk: np.ndarray) -> Optional[TranscriptionResult]:
        if self._model is None:
            return None

        with self._lock:
            self._buffer = np.concatenate([self._buffer, audio_chunk])

            if len(self._buffer) < self._min_samples:
                return None

            audio_copy = self._buffer.copy()

        try:
            segments, info = self._model.transcribe(
                audio_copy,
                language="en",
                beam_size=2,
                best_of=2,
                patience=1.2,
                length_penalty=1.0,
                temperature=(0.0, 0.2, 0.4),
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.5,
                condition_on_previous_text=False,
                initial_prompt="",
                word_timestamps=False,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=800,
                    speech_pad_ms=400,
                    threshold=0.35,
                ),
            )

            texts = []
            total_conf = 0.0
            count = 0
            for segment in segments:
                text = segment.text.strip()
                if text:
                    texts.append(text)
                    total_conf += 1.0 - segment.avg_logprob
                    count += 1

            if texts:
                combined_text = " ".join(texts)
                avg_conf = total_conf / count if count > 0 else 0.0

                if combined_text != self._last_text:
                    self._last_text = combined_text
                    with self._lock:
                        self._buffer = self._buffer[-self._overlap_samples:]

                    return TranscriptionResult(
                        text=combined_text,
                        language=info.language,
                        confidence=avg_conf,
                        timestamp_ms=int(time.time() * 1000),
                    )
                else:
                    with self._lock:
                        self._buffer = self._buffer[-self._overlap_samples:]

            return None

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    def reset_buffer(self):
        with self._lock:
            self._buffer = np.array([], dtype=np.float32)
            self._last_text = ""