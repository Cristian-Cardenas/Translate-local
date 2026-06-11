import pyaudiowpatch as pyaudio
import numpy as np
import threading
import queue
import time
from typing import Callable, Optional, List, Tuple

import logging

logger = logging.getLogger(__name__)


class AudioCapture:
    def __init__(self, chunk_ms: int = 66, target_sample_rate: int = 16000, noise_reduce: bool = True):
        self.chunk_ms = chunk_ms
        self.target_sample_rate = target_sample_rate
        self.noise_reduce = noise_reduce
        self._callback: Optional[Callable[[np.ndarray], None]] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream = None
        self._device_index: Optional[int] = None
        self._audio_queue = queue.Queue(maxsize=30)
        self._device_sample_rate = 48000
        self._device_channels = 2
        self._nr_module = None
        if noise_reduce:
            try:
                import noisereduce as nr
                self._nr_module = nr
                logger.info("Noise reduction enabled (noisereduce)")
            except ImportError:
                logger.warning("noisereduce not installed, noise reduction disabled")
                self.noise_reduce = False

    def enumerate_devices(self) -> List[Tuple[int, str, bool]]:
        devices = []
        self._pa = pyaudio.PyAudio()
        
        # Find default output device name
        default_output_name = ""
        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_output_idx = wasapi_info.get("defaultOutputDevice", -1)
            if default_output_idx >= 0:
                default_output_info = self._pa.get_device_info_by_index(default_output_idx)
                default_output_name = default_output_info.get("name", "")
        except OSError:
            pass

        for i in range(self._pa.get_device_count()):
            try:
                info = self._pa.get_device_info_by_index(i)
                if info.get("isLoopbackDevice", False) and info.get("maxInputChannels", 0) > 0:
                    # Check if this loopback matches the default output device
                    is_default = default_output_name in info.get("name", "")
                    devices.append((int(info["index"]), info["name"], is_default))
            except Exception:
                continue
        return devices

    def set_device(self, device_index: int) -> bool:
        if self._running:
            return False
        self._device_index = device_index
        return True

    def set_callback(self, callback: Callable[[np.ndarray], None]):
        self._callback = callback

    def start(self) -> bool:
        if self._running or not self._callback:
            return False

        self._pa = pyaudio.PyAudio()
        try:
            if self._device_index is not None:
                device_info = self._pa.get_device_info_by_index(self._device_index)
            else:
                # Find default loopback device (matching default output by name)
                wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_output_idx = wasapi_info.get("defaultOutputDevice", -1)
                default_output_name = ""
                if default_output_idx >= 0:
                    default_output_info = self._pa.get_device_info_by_index(default_output_idx)
                    default_output_name = default_output_info.get("name", "")
                
                device_info = None
                for i in range(self._pa.get_device_count()):
                    info = self._pa.get_device_info_by_index(i)
                    if info.get("isLoopbackDevice", False) and info.get("maxInputChannels", 0) > 0:
                        if default_output_name and default_output_name in info.get("name", ""):
                            device_info = info
                            break
                if device_info is None:
                    # Fallback to first loopback device
                    for i in range(self._pa.get_device_count()):
                        info = self._pa.get_device_info_by_index(i)
                        if info.get("isLoopbackDevice", False) and info.get("maxInputChannels", 0) > 0:
                            device_info = info
                            break

            if device_info is None or not device_info.get("isLoopbackDevice", False):
                raise RuntimeError("No loopback device found")

            self._device_sample_rate = int(device_info.get("defaultSampleRate", 48000))
            self._device_channels = device_info.get("maxInputChannels", 2)
            device_chunk_samples = int(self._device_sample_rate * self.chunk_ms / 1000)

            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self._device_channels,
                rate=self._device_sample_rate,
                input=True,
                input_device_index=int(device_info["index"]),
                frames_per_buffer=device_chunk_samples,
                stream_callback=self._audio_callback,
            )

            self._running = True
            self._thread = threading.Thread(target=self._process_queue, daemon=True)
            self._thread.start()
            self._stream.start_stream()
            return True

        except Exception as e:
            print(f"Audio start error: {e}")
            self.stop()
            return False

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self._running:
            try:
                audio_data = np.frombuffer(in_data, dtype=np.float32)
                # Convert stereo to mono if needed
                if self._device_channels > 1:
                    audio_data = audio_data.reshape(-1, self._device_channels).mean(axis=1)
                # Resample to target sample rate (16000)
                if self._device_sample_rate != self.target_sample_rate:
                    ratio = self.target_sample_rate / self._device_sample_rate
                    new_length = int(len(audio_data) * ratio)
                    indices = np.linspace(0, len(audio_data) - 1, new_length)
                    audio_data = np.interp(indices, np.arange(len(audio_data)), audio_data).astype(np.float32)
                # Apply noise reduction
                if self.noise_reduce and self._nr_module is not None:
                    try:
                        audio_data = self._nr_module.reduce_noise(
                            y=audio_data,
                            sr=self.target_sample_rate,
                            stationary=False,
                            prop_decrease=0.8
                        )
                    except Exception:
                        pass
                self._audio_queue.put_nowait(audio_data)
            except queue.Full:
                pass
        return (None, pyaudio.paContinue)

    def _process_queue(self):
        while self._running:
            try:
                data = self._audio_queue.get(timeout=0.1)
                if self._callback:
                    self._callback(data)
            except queue.Empty:
                continue

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._running
