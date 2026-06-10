import pyaudiowpatch as pyaudio
pa = pyaudio.PyAudio()
for idx in [19, 20, 21, 22]:
    info = pa.get_device_info_by_index(idx)
    print('Device %d: %s' % (idx, info['name']))
    print('  Default sample rate:', info['defaultSampleRate'])
    print('  Max input channels:', info['maxInputChannels'])
    print()