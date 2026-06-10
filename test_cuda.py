from faster_whisper import WhisperModel
m = WhisperModel('tiny.en', device='cuda', compute_type='float16')
print('CUDA OK')