import threading
import pyaudio
import os
import aubio
import numpy as np
import logging


class DeviceDetector:
    def __init__(self):
        self.p = pyaudio.PyAudio()

    def list_audio_devices(self):
        try:
            info = self.p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            for i in range(0, numdevices):
                if (self.p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    logging.info("Input Device id %s - %s", i, self.p.get_device_info_by_host_api_device_index(0, i).get('name'))
        except Exception:
            logging.exception('Error listing audio devices')

    def __del__(self):
        self.p.terminate()

def list_input_devices():
    p = pyaudio.PyAudio()
    devices = []
    try:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) > 0:
                devices.append({
                    'id': i,
                    'name': info.get('name'),
                    'defaultSampleRate': int(info.get('defaultSampleRate') or 0),
                    'maxInputChannels': int(info.get('maxInputChannels') or 0)
                })
        logging.debug('Found %d input devices', len(devices))
    except Exception:
        logging.exception('Error listing input devices')
    finally:
        p.terminate()
    return devices

def resolve_device_index(pyaudio_instance, config_entry):
    """Resolve a configured device entry to an actual device index.
    Strategy: exact name match -> substring match -> stored id fallback -> None
    """
    target_name = config_entry.get('name')
    # 1) exact name
    if target_name:
        for i in range(pyaudio_instance.get_device_count()):
            try:
                info = pyaudio_instance.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get('maxInputChannels', 0) <= 0:
                continue
            if info.get('name') == target_name:
                return i
    # 2) substring match (case-insensitive)
    if target_name:
        lower = target_name.lower()
        for i in range(pyaudio_instance.get_device_count()):
            try:
                info = pyaudio_instance.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get('maxInputChannels', 0) <= 0:
                continue
            if lower in (info.get('name') or '').lower():
                return i
    # 3) fallback to stored id if it exists and has input channels
    stored_id = config_entry.get('id')
    if stored_id is not None:
        try:
            info = pyaudio_instance.get_device_info_by_index(stored_id)
            if info.get('maxInputChannels', 0) > 0:
                return stored_id
        except Exception:
            pass
    return None

class BeatDetector(threading.Thread):
    def __init__(self, method, buffer_size, sample_rate, channels, format, input_device_index=None, window_multiple=4):
        threading.Thread.__init__(self)
        self.p = pyaudio.PyAudio()
        # make buffer and window sizes explicit and configurable
        self.buffer_size = buffer_size
        self.window_multiple = window_multiple
        win_size = buffer_size * window_multiple
        # determine samplerate from device when available to avoid clock mismatch calibration
        self.sample_rate = int(sample_rate) if sample_rate else None
        if input_device_index is not None:
            try:
                dev_info = self.p.get_device_info_by_index(input_device_index)
                dev_rate = dev_info.get('defaultSampleRate')
                if dev_rate:
                    self.sample_rate = int(dev_rate)
                    if os.environ.get('BPM_DEBUG') == '1':
                        print(f"Using device sample rate {self.sample_rate} for input {input_device_index}")
            except Exception:
                # fallback to provided sample_rate
                pass
        if not self.sample_rate:
            # fallback to a sane default
            self.sample_rate = int(44100)

        # use named arguments to avoid ambiguity
        self.tempo = aubio.tempo(method=method, buf_size=win_size, hop_size=buffer_size, samplerate=self.sample_rate)
        # open stream with the device sample rate to prevent clock drift bias
        self.stream = self.p.open(format=format, channels=channels, rate=self.sample_rate, input=True, frames_per_buffer=buffer_size, input_device_index=input_device_index)
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
        # guard against buffer overflow by allowing non-blocking read to drop frames when needed
        try:
            data = self.stream.read(self.buffer_size, exception_on_overflow=False)
        except Exception:
            return
        samples = np.frombuffer(data, dtype=aubio.float_type)
        is_beat = self.tempo(samples)
        if is_beat:
            # this_beat = int(self.tempo.get_last_s())
            raw_bpm = self.tempo.get_bpm()
            if raw_bpm:
                bpm_estimate = raw_bpm
                self.bpm_estimates.append(bpm_estimate)
                # keep last N seconds estimates
                self.bpm_estimates = self.bpm_estimates[-self.rolling_window_seconds:]
                # use median for robustness
                try:
                    median_bpm = float(np.median(self.bpm_estimates))
                except Exception:
                    median_bpm = float(bpm_estimate)
                self.bpm = round(median_bpm, 1)
                # optional debug print controlled by env var
                if os.environ.get('BPM_DEBUG') == '1':
                    print(f"raw={raw_bpm:.3f}, median={self.bpm:.2f}")
