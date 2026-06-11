import sys
import os
import threading
from pathlib import Path

cuda_path = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin"
if os.path.exists(cuda_path):
    os.environ["PATH"] = cuda_path + ";" + os.environ["PATH"]

sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.pipeline import Pipeline
from ui.overlay import OverlayWindow


def main():
    models_dir = Path(__file__).parent / "models"
    models_dir.mkdir(exist_ok=True)

    pipeline = Pipeline(models_dir=str(models_dir))
    overlay = OverlayWindow()

    def on_transcription(result):
        pass

    def on_translation(original, translated, ts):
        overlay.update_subtitle(english=original, spanish=translated)

    def on_error(msg):
        print(f"Error: {msg}")
        overlay.update_subtitle(english=f"Error: {msg}", spanish="")

    def on_devices(devices):
        overlay.set_devices(devices)

    def on_start():
        if pipeline.start():
            overlay.hide_settings_and_show_overlay()

    def on_device_change(device_index):
        pipeline.set_device(device_index)

    def on_silence():
        overlay.clear_subtitle()

    pipeline.set_callbacks(
        on_transcription=on_transcription,
        on_translation=on_translation,
        on_error=on_error,
        on_device_list=on_devices,
        on_silence=on_silence,
    )
    overlay.set_start_callback(on_start)
    overlay.set_device_change_callback(on_device_change)

    def init_and_enumerate():
        if pipeline.initialize():
            pipeline.enumerate_devices()

    threading.Thread(target=init_and_enumerate, daemon=True).start()

    overlay.show_settings_first()
    overlay.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
