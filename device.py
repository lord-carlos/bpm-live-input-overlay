import pyaudio

p = pyaudio.PyAudio()

# List all available audio input devices
for i in range(p.get_device_count()):
    device_info = p.get_device_info_by_index(i)
    if device_info['maxInputChannels'] > 0:
        print(f"Device {i}: {device_info['name']}")

p.terminate()
