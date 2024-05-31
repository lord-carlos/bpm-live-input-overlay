import pyaudio
import numpy as np
import aubio
import argparse
import threading
import json
import time

class DeviceDetector:
    def __init__(self):
        self.p = pyaudio.PyAudio()

    def list_audio_devices(self):
        info = self.p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        for i in range(0, numdevices):
            if (self.p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                print("Input Device id ", i, " - ", self.p.get_device_info_by_host_api_device_index(0, i).get('name'))

    def __del__(self):
        self.p.terminate()

class BeatDetector(threading.Thread):
    def __init__(self, method, buffer_size, sample_rate, channels, format, input_device_index=None):
        threading.Thread.__init__(self)
        self.p = pyaudio.PyAudio()
        self.tempo = aubio.tempo(method, buffer_size*4, buffer_size, sample_rate)
        self.stream = self.p.open(format=format, channels=channels, rate=sample_rate, input=True, frames_per_buffer=buffer_size, input_device_index=input_device_index)
        self.bpm_estimates = []
        self.rolling_window_seconds = 5
        self.bpm = 0
        self.running = True

    def run(self):
        print("Starting to listen, press Ctrl+C to stop")
        try:
            while self.running:
                self.detect_beat()
        except KeyboardInterrupt:
            print("\nStopping")
            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()

    def stop(self):
        self.running = False

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
                # self.bpm = sum(self.bpm_estimates) / len(self.bpm_estimates)
                self.bpm = bpm_estimate
                # print(f"\rBeat at estimated BPM: {bpm_estimate:.2f}, rolling {self.rolling_window_seconds}s average BPM: {self.bpm:.1f} ", end='', flush=True)

class BpmDisplay:
    def __init__(self, beat_detectors):
        self.beat_detectors = beat_detectors

    def display_bpms(self):
        print("\n" * 10)
        while True:
            print("\r\033[K" + ",       ".join([f"{i}: {beat_detector.bpm:.1f}" for i, beat_detector in enumerate(self.beat_detectors)]), end='', flush=True)
            time.sleep(1)

# Constants
BUFFER_SIZE = 256
CHANNELS = 1
FORMAT = pyaudio.paFloat32
METHOD = "default"
SAMPLE_RATE = 44100

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--list-devices", help="List all audio input devices", action="store_true")
args = parser.parse_args()

if args.list_devices:
    device_detector = DeviceDetector()
    device_detector.list_audio_devices()
else:
    # Load config file
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Create BeatDetector instances
    beat_detectors = []
    for input_device in config['input_devices']:
        beat_detector = BeatDetector(METHOD, BUFFER_SIZE, SAMPLE_RATE, CHANNELS, FORMAT, input_device)
        beat_detector.start()
        beat_detectors.append(beat_detector)

    # Create BpmDisplay instance and start it
    bpm_display = BpmDisplay(beat_detectors)
    try:
        bpm_display.display_bpms()
    except KeyboardInterrupt:
        print("\nStopping")
        for beat_detector in beat_detectors:
            beat_detector.stop()