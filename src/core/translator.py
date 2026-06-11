from deep_translator import GoogleTranslator
import threading
from typing import Optional


class Translator:
    def __init__(self, model_dir: str = "models"):
        self._translator = None
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> bool:
        try:
            self._translator = GoogleTranslator(source="en", target="es")
            self._initialized = True
            return True
        except Exception as e:
            print(f"Translator init error: {e}")
            self._initialized = False
            return False

    def translate(self, text: str) -> str:
        if not text.strip() or not self._initialized or not self._translator:
            return text

        with self._lock:
            try:
                result = self._translator.translate(text)
                return result if result else text
            except Exception as e:
                print(f"Translation error: {e}")
                return text
