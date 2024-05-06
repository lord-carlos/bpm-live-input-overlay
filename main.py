import pyaudio
import numpy as np
import aubio
import argparse

class BeatDetector:
    def __init__(self, method, buffer_size, sample_rate, channels, format, input_device_index=None):
        self.p = pyaudio.PyAudio()
        self.tempo = aubio.tempo(method, buffer_size*4, buffer_size, sample_rate)
        self.stream = self.p.open(format=format, channels=channels, rate=sample_rate, input=True, frames_per_buffer=buffer_size, input_device_index=input_device_index)
        self.bpm_estimates = []
        self.rolling_window_seconds = 5

    def list_audio_devices(self):
        info = self.p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        for i in range(0, numdevices):
            if (self.p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                print("Input Device id ", i, " - ", self.p.get_device_info_by_host_api_device_index(0, i).get('name'))


    def detect_beat(self):
        data = self.stream.read(BUFFER_SIZE)
        samples = np.frombuffer(data, dtype=aubio.float_type)
        is_beat = self.tempo(samples)
        if is_beat:
            this_beat = int(self.tempo.get_last_s())
            bpm_estimate = self.tempo.get_bpm()*0.993
            if bpm_estimate:
                self.bpm_estimates.append(bpm_estimate)
                self.bpm_estimates = self.bpm_estimates[-self.rolling_window_seconds:]
                bpm_average = sum(self.bpm_estimates) / len(self.bpm_estimates)
                print(f"\rBeat at estimated BPM: {bpm_estimate:.2f}, rolling {self.rolling_window_seconds}s average BPM: {bpm_average:.1f} ", end='', flush=True)
                
                
    def start(self):
        print("Starting to listen, press Ctrl+C to stop")
        try:
            while True:
                self.detect_beat()
        except KeyboardInterrupt:
            print("\nStopping")
            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()

# Constants
BUFFER_SIZE = 256
CHANNELS = 1
FORMAT = pyaudio.paFloat32
METHOD = "default"
SAMPLE_RATE = 44100

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--list-devices", help="List all audio input devices", action="store_true")
parser.add_argument("--input-device", type=int, help="Specify the input device index")
args = parser.parse_args()

# Create BeatDetector instance and start it
beat_detector = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, args.input_device)

if args.list_devices:
    beat_detector.list_audio_devices()
else:
    beat_detector.start()
