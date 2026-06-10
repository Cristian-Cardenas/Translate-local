from src.core.pipeline import Pipeline
import time

p = Pipeline()
ok = p.initialize()
print('Pipeline init:', ok)
devices = p.enumerate_devices()
print('Devices:', len(devices))
for d in devices:
    print('  %d: %s (default=%s)' % (d[0], d[1], d[2]))
# Seleccionar el último (Realtek speakers loopback)
p.set_device(devices[-1][0])
print('Selected:', devices[-1][1])
ok = p.start()
print('Start:', ok)
time.sleep(5)
print('Running...')
p.stop()
print('Stopped')