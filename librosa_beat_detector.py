"""Librosa-based beat detector with rolling buffer."""

import numpy as np
import pyaudio
import librosa
import time
import os

from beat_detector_base import BaseBeatDetector


# =============================================================================
# CONFIGURABLE PARAMETERS - Tune these for CPU/accuracy tradeoff
# =============================================================================

# Audio capture settings
SAMPLE_RATE = 44100          # Lower = less CPU (22050 recommended for Pi, 44100 for high accuracy)
BUFFER_SIZE = 1024           # PyAudio buffer size per read (samples)
CHANNELS = 2                 # Mono audio # 1 bad results.

# Rolling buffer settings
BUFFER_DURATION = 8.0       # Seconds of audio to keep in rolling buffer
UPDATE_INTERVAL = 8.0        # Seconds between BPM recalculations

# Librosa beat_track parameters
HOP_LENGTH = 256             # Hop length for onset detection (larger = faster, less accurate) default: 256
START_BPM = 120.0            # Starting tempo estimate for beat tracking

# Smoothing
ENABLE_SMOOTHING = True      # Enable smoothing of BPM over time (exponential moving average)
SMOOTHING_ALPHA = 0.6        # Weight for new detection (0.0-1.0). Higher = more responsive.

# Onset strength parameters (for advanced tuning if needed)
DETREND = False              # Detrend onset envelope (can help with some audio)
CENTER = True                # Center the onset envelope
FMAX = 8000.0                # Max frequency for mel spectrogram (lower = less CPU) default: 8000.0
FMIN = 20.0                  # Min frequency for mel spectrogram # default: 30.0 

# Debug
DEBUG = os.environ.get("BPM_DEBUG", "0") == "1"


class LibrosaBeatDetector(BaseBeatDetector):
    """
    Beat detector using librosa with a rolling audio buffer.
    
    Captures audio continuously, maintains a rolling buffer of BUFFER_DURATION seconds,
    and recalculates BPM every UPDATE_INTERVAL seconds.
    """

    def __init__(self, input_device_index=None):
        super().__init__(input_device_index)
        
        self.sample_rate = SAMPLE_RATE
        self.buffer_size = BUFFER_SIZE
        self.channels = CHANNELS
        
        # Calculate buffer sizes
        self.buffer_samples = int(BUFFER_DURATION * self.sample_rate)
        self.update_samples = int(UPDATE_INTERVAL * self.sample_rate)
        
        # Rolling audio buffer (circular buffer using numpy)
        self.audio_buffer = np.zeros(self.buffer_samples, dtype=np.float32)
        self.samples_since_update = 0
        
        # PyAudio setup
        self.pa = None
        self.stream = None

    def run(self):
        """Main thread loop - capture audio and periodically calculate BPM."""
        self.running = True
        self.pa = pyaudio.PyAudio()
        
        # Get device info to check native sample rate
        if self.input_device_index is not None:
            device_info = self.pa.get_device_info_by_index(self.input_device_index)
            native_rate = int(device_info.get('defaultSampleRate', 44100))
            if DEBUG:
                print(f"[LibrosaBeatDetector] Device native rate: {native_rate}, using: {self.sample_rate}")
        
        try:
            self.stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.input_device_index,
                frames_per_buffer=self.buffer_size,
            )
        except Exception as e:
            print(f"[LibrosaBeatDetector] Error opening audio stream: {e}")
            self.running = False
            return
        
        if DEBUG:
            print(f"[LibrosaBeatDetector] Started - buffer: {BUFFER_DURATION}s, update: {UPDATE_INTERVAL}s")
        
        while self.running:
            try:
                # Read audio chunk
                audio_data = self.stream.read(self.buffer_size, exception_on_overflow=False)
                samples = np.frombuffer(audio_data, dtype=np.float32)
                
                # Roll buffer and add new samples
                self.audio_buffer = np.roll(self.audio_buffer, -len(samples))
                self.audio_buffer[-len(samples):] = samples
                
                self.samples_since_update += len(samples)
                
                # Recalculate BPM at update interval
                if self.samples_since_update >= self.update_samples:
                    self._calculate_bpm()
                    self.samples_since_update = 0
                    
            except Exception as e:
                if self.running:
                    print(f"[LibrosaBeatDetector] Error reading audio: {e}")
                    time.sleep(0.1)
        
        self._cleanup()

    def _calculate_bpm(self):
        """Calculate BPM from the current audio buffer using Inter-Beat Intervals (IBI)."""
        try:
            # Skip if buffer is mostly silence
            if np.max(np.abs(self.audio_buffer)) < 0.01:
                if DEBUG:
                    print("[LibrosaBeatDetector] Buffer is silent, skipping")
                return
            
            # Calculate onset strength envelope
            onset_env = librosa.onset.onset_strength(
                y=self.audio_buffer,
                sr=self.sample_rate,
                hop_length=HOP_LENGTH,
                fmax=FMAX,
                center=CENTER,
                detrend=DETREND,
            )
            
            # Use beat_track to find beat locations
            # tightness=100 helps lock onto stable beats in electronic music
            tempo, beats = librosa.beat.beat_track(
                onset_envelope=onset_env,
                sr=self.sample_rate,
                hop_length=HOP_LENGTH,
                start_bpm=START_BPM,
                tightness=100
            )
            
            if len(beats) < 2:
                if DEBUG:
                    print("[LibrosaBeatDetector] Not enough beats detected")
                return

            # Refine beat locations using parabolic interpolation for sub-frame accuracy
            refined_beats = []
            for b in beats:
                if 0 < b < len(onset_env) - 1:
                    alpha = onset_env[b - 1]
                    beta = onset_env[b]
                    gamma = onset_env[b + 1]
                    
                    # Only interpolate if distinct local peak
                    if beta >= alpha and beta >= gamma and (alpha - 2 * beta + gamma) != 0:
                        p = 0.5 * (alpha - gamma) / (alpha - 2 * beta + gamma)
                        refined_beats.append(b + p)
                    else:
                        refined_beats.append(b)
                else:
                    refined_beats.append(b)
            
            refined_beats = np.array(refined_beats)

            # Analyze beat timestamps for higher precision
            beat_times = refined_beats * HOP_LENGTH / self.sample_rate
            ibis = np.diff(beat_times)

            # Filter out unreasonable intervals (e.g. outside 40-220 BPM range)
            # 220 BPM ~= 0.27s, 40 BPM = 1.5s
            valid_ibis = ibis[(ibis > 0.27) & (ibis < 1.5)]
            
            if len(valid_ibis) > 0:
                # Use median to ignore outliers (missed beats etc)
                median_ibi = np.median(valid_ibis)
                raw_bpm = 60.0 / median_ibi
                
                # Apply smoothing if enabled
                if ENABLE_SMOOTHING and self.bpm > 0:
                    # Exponential moving average
                    new_bpm = (self.bpm * (1 - SMOOTHING_ALPHA)) + (raw_bpm * SMOOTHING_ALPHA)
                    self.bpm = round(new_bpm, 1)
                else:
                    self.bpm = round(raw_bpm, 1)
                
                if DEBUG:
                    if ENABLE_SMOOTHING:
                        print(f"[LibrosaBeatDetector] Raw: {raw_bpm:.2f} BPM, Smoothed: {self.bpm} BPM")
                    else:
                        print(f"[LibrosaBeatDetector] BPM: {self.bpm}")
            elif DEBUG:
                print("[LibrosaBeatDetector] No valid beat intervals found")
                    
        except Exception as e:
            if DEBUG:
                print(f"[LibrosaBeatDetector] Error calculating BPM: {e}")

    def _cleanup(self):
        """Clean up audio resources."""
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.pa:
            try:
                self.pa.terminate()
            except Exception:
                pass

    def stop(self):
        """Signal the thread to stop."""
        self.running = False
