import pyaudiowpatch as pyaudio
pa = pyaudio.PyAudio()
wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
default_out = wasapi.get('defaultOutputDevice')
print('Default output device index:', default_out)
if default_out >= 0:
    info = pa.get_device_info_by_index(default_out)
    print('Default output name:', info['name'])
print()
print('Loopback devices:')
for i in range(pa.get_device_count()):
    info = pa.get_device_info_by_index(i)
    if info.get('isLoopbackDevice', False) and info.get('maxInputChannels', 0) > 0:
        print('  %d: %s' % (int(info['index']), info['name']))