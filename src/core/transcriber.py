from faster_whisper import WhisperModel
import numpy as np
import threading
import time
from typing import Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    timestamp_ms: int
    is_final: bool


class Transcriber:
    def __init__(self, model_path: str = "tiny.en", device: str = "cuda", compute_type: str = "float16"):
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._buffer = np.array([], dtype=np.float32)
        self._lock = threading.Lock()
        self._min_samples = 16000 * 2
        self._max_samples = 16000 * 30

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
            if len(self._buffer) > self._max_samples:
                self._buffer = self._buffer[-self._max_samples:]

            if len(self._buffer) < self._min_samples:
                logger.debug(f"Buffer too small: {len(self._buffer)} < {self._min_samples}")
                return None

            audio_copy = self._buffer.copy()
            logger.debug(f"Transcribing buffer: {len(audio_copy)} samples ({len(audio_copy)/16000:.1f}s)")

        try:
            segments, info = self._model.transcribe(
                audio_copy,
                language="en",
                beam_size=1,
                best_of=1,
                patience=1.0,
                length_penalty=1.0,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
                initial_prompt=None,
                word_timestamps=False,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            result = None
            for i, segment in enumerate(segments):
                logger.debug(f"Segment {i}: '{segment.text}' (start={segment.start:.2f}, end={segment.end:.2f}, avg_logprob={segment.avg_logprob:.4f})")
                if segment.text.strip():
                    result = TranscriptionResult(
                        text=segment.text.strip(),
                        language=info.language,
                        confidence=1.0 - segment.avg_logprob,
                        timestamp_ms=int((segment.start + segment.end) * 500),
                        is_final=(i == 0),
                    )
                    break

            return result

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    def reset_buffer(self):
        with self._lock:
            self._buffer = np.array([], dtype=np.float32)