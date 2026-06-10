import argostranslate.translate
import argostranslate.package
import threading
from pathlib import Path
from typing import Optional


class Translator:
    def __init__(self, model_dir: str = "models"):
        self.model_dir = Path(model_dir)
        self._translation = None
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> bool:
        try:
            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            en_es = [p for p in available if p.from_code == "en" and p.to_code == "es"]
            if en_es:
                pkg = en_es[0]
                pkg.download()
                pkg.install()

            installed = argostranslate.translate.get_installed_languages()
            en_lang = next((l for l in installed if l.code == "en"), None)
            es_lang = next((l for l in installed if l.code == "es"), None)

            if en_lang and es_lang:
                self._translation = en_lang.get_translation(es_lang)
                self._initialized = True
                return True
        except Exception as e:
            print(f"Translator init error: {e}")

        self._initialized = False
        return False

    def translate(self, text: str) -> str:
        if not text.strip() or not self._initialized or not self._translation:
            return text

        with self._lock:
            try:
                return self._translation.translate(text)
            except Exception as e:
                print(f"Translation error: {e}")
                return text