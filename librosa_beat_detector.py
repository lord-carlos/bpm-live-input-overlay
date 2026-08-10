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
UPDATE_INTERVAL = 2.0        # Seconds between BPM recalculations

# Librosa beat_track parameters
HOP_LENGTH = 256             # Hop length for onset detection (larger = faster, less accurate) default: 256
START_BPM = 120.0            # Starting tempo estimate for beat tracking

# BPM detection range - raw readings are corrected into this range
MIN_BPM = 90.0               # Minimum detectable BPM
MAX_BPM = 150.0              # Maximum detectable BPM

# Analysis runs at this rate (librosa's native rate; no tempo information lost,
# the onset analysis discards everything above FMAX anyway)
ANALYSIS_SAMPLE_RATE = 22050

# Harmonic (octave) correction: raw readings are scored at these tempo multiples
# against a comb sum of the onset autocorrelation (1x-4x the beat period, so a
# true 4/4 tempo also collects energy at the 2-beat and bar level), weighted by
# a log-normal prior around the perceptual tempo center. Triplet-based factors
# need slightly stronger evidence (most music is 4/4). Fixes classic octave
# errors (163 BPM for a 122 BPM song, 92 BPM for a 138 BPM song, ...).
HARMONIC_FACTORS = (0.5, 2 / 3, 0.75, 1.0, 4 / 3, 1.5, 2.0)
PRIOR_CENTER_BPM = 120.0     # Perceptual tempo prior center
PRIOR_STD_OCTAVES = 1.0      # Prior width in octaves
COMB_WEIGHTS = (1.0, 0.5, 1 / 3, 0.25)
OCTAVE_FACTORS = (0.5, 1.0, 2.0)
TRIPLET_FACTOR_PENALTY = 0.95

# Stabilization: small deviations are fine-tracked with an EMA; larger tempo
# changes must repeat for SWITCH_CONFIRM_READINGS passes (~2s each) before
# switching, preventing jumps from single bad readings.
SMOOTHING_ALPHA = 0.6        # EMA weight for new readings during fine tracking
FINE_TRACK_TOLERANCE = 0.03  # <=3% deviation counts as fine tracking
SWITCH_CONFIRM_READINGS = 3  # Consecutive readings needed to confirm a change

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

        # Tempo change confirmation state (hysteresis)
        self._pending_bpm = None     # Candidate tempo awaiting confirmation
        self._pending_count = 0      # Consecutive readings agreeing with candidate
        
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
            
            # Update sample rate to match device native rate (avoid resampling artifacts)
            if native_rate != self.sample_rate:
                if DEBUG:
                    print(f"[LibrosaBeatDetector] Switching to native device rate: {native_rate} (was {self.sample_rate})")
                self.sample_rate = native_rate
                
                # Recalculate buffer sizes based on new rate
                self.buffer_samples = int(BUFFER_DURATION * self.sample_rate)
                self.update_samples = int(UPDATE_INTERVAL * self.sample_rate)
                
                # Re-initialize rolling buffer with new size
                self.audio_buffer = np.zeros(self.buffer_samples, dtype=np.float32)
            elif DEBUG:
                print(f"[LibrosaBeatDetector] Device rate matches default: {self.sample_rate}")
        
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

                # Mix interleaved stereo down to mono, so the buffer holds
                # BUFFER_DURATION seconds of actual audio content
                if self.channels == 2:
                    samples = samples.reshape(-1, 2).mean(axis=1)

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

            # Resample to the analysis rate (librosa's native rate; tempo is a
            # ~2-3 Hz amplitude modulation, so nothing relevant is lost)
            mono_audio = self.audio_buffer
            if self.sample_rate != ANALYSIS_SAMPLE_RATE:
                mono_audio = librosa.resample(
                    mono_audio,
                    orig_sr=self.sample_rate,
                    target_sr=ANALYSIS_SAMPLE_RATE,
                )
            sr = ANALYSIS_SAMPLE_RATE

            # Calculate onset strength envelope
            onset_env = librosa.onset.onset_strength(
                y=mono_audio,
                sr=sr,
                hop_length=HOP_LENGTH,
                fmax=FMAX,
                center=CENTER,
                detrend=DETREND,
            )

            # Anchor the tracker to the stabilized tempo, or to the pending
            # candidate while a tempo change is being confirmed. This prevents
            # octave jumps (60 vs 120) and helps lock on.
            if self._pending_bpm is not None:
                current_start_bpm = self._pending_bpm
            elif self.bpm > 0:
                current_start_bpm = self.bpm
            else:
                current_start_bpm = START_BPM

            # Use beat_track to find beat locations
            # tightness=100 helps lock onto stable beats in electronic music
            tempo, beats = librosa.beat.beat_track(
                onset_envelope=onset_env,
                sr=sr,
                hop_length=HOP_LENGTH,
                start_bpm=current_start_bpm,
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
            beat_times = refined_beats * HOP_LENGTH / sr
            ibis = np.diff(beat_times)

            # Wide interval gate (half/double the BPM range): harmonic errors
            # are corrected below instead of being discarded here
            max_ibi = 60.0 / (MIN_BPM / 2)
            min_ibi = 60.0 / (MAX_BPM * 2)
            valid_ibis = ibis[(ibis > min_ibi) & (ibis < max_ibi)]

            if len(valid_ibis) == 0:
                if DEBUG:
                    print("[LibrosaBeatDetector] No usable beat intervals, holding previous BPM")
                return

            # Cluster Averaging:
            # 1. Get the median to find the "center" of the rhythm suitable for rejecting outliers
            median_ibi = np.median(valid_ibis)

            # 2. Select intervals within 5% of the median (rejects outliers like missed/double beats)
            tolerance = 0.05
            cluster_ibis = valid_ibis[np.abs(valid_ibis - median_ibi) <= (tolerance * median_ibi)]

            # 3. Take the MEAN of this cluster to get sub-sample precision
            # This fixes the "snapping" issue of just using the single median value
            if len(cluster_ibis) > 0:
                mean_ibi = np.mean(cluster_ibis)
                raw_bpm = 60.0 / mean_ibi
            else:
                raw_bpm = 60.0 / median_ibi

            # Correct octave/harmonic errors into the configured BPM range
            corrected_bpm = self._correct_harmonics(raw_bpm, onset_env, sr)

            # Stabilize (EMA fine tracking + confirmed switching)
            self._update_stabilized_bpm(corrected_bpm)

        except Exception as e:
            if DEBUG:
                print(f"[LibrosaBeatDetector] Error calculating BPM: {e}")

    def _correct_harmonics(self, raw_bpm, onset_env, sr):
        """
        Map a raw tempo reading into [MIN_BPM, MAX_BPM] by scoring harmonic
        candidates (half, 2/3, 3/4, same, 4/3, 3/2, double) against the onset
        envelope autocorrelation.

        Each candidate is scored with a comb sum (autocorrelation at 1x-4x its
        beat period, so a true 4/4 tempo also collects energy at the 2-beat and
        bar level), a log-normal perceptual prior, and a small penalty for
        triplet-based factors.

        Fixes classic octave errors (e.g. 163 BPM detected for a 122 BPM song,
        or 92 BPM for a 138 BPM song with a 3-eighth-note accent pattern).
        """
        candidates = []  # (bpm, factor)
        for factor in HARMONIC_FACTORS:
            cand = raw_bpm * factor
            if MIN_BPM <= cand <= MAX_BPM and all(
                abs(cand - c) > 0.01 for c, _ in candidates
            ):
                candidates.append((cand, factor))

        if not candidates:
            return float(np.clip(raw_bpm, MIN_BPM, MAX_BPM))
        if len(candidates) == 1:
            return candidates[0][0]

        # Normalized autocorrelation of the onset envelope
        env = onset_env - np.mean(onset_env)
        ac = np.correlate(env, env, mode="full")[len(env) - 1:]
        if len(ac) == 0 or ac[0] <= 0:
            return float(np.clip(raw_bpm, MIN_BPM, MAX_BPM))
        ac = ac / ac[0]

        fps = sr / HOP_LENGTH

        def ac_at_lag(lag):
            """Autocorrelation at a fractional lag (linear interpolation)."""
            lo = int(np.floor(lag))
            if lo >= len(ac) - 1:
                return 0.0
            frac = lag - lo
            return float(ac[lo] * (1.0 - frac) + ac[lo + 1] * frac)

        def comb_pulse(bpm):
            """Weighted autocorrelation sum at 1x-4x the beat period."""
            lag = fps * 60.0 / bpm
            return float(
                sum(w * ac_at_lag(k * lag) for k, w in enumerate(COMB_WEIGHTS, 1))
            )

        best_bpm = candidates[0][0]
        best_score = -1.0
        for cand, factor in candidates:
            pulse = comb_pulse(cand)
            prior = float(
                np.exp(
                    -0.5
                    * (np.log2(cand / PRIOR_CENTER_BPM) / PRIOR_STD_OCTAVES) ** 2
                )
            )
            factor_weight = 1.0 if factor in OCTAVE_FACTORS else TRIPLET_FACTOR_PENALTY
            score = pulse * prior * factor_weight
            if DEBUG:
                print(
                    f"[LibrosaBeatDetector]   candidate {cand:6.1f} BPM (x{factor:.2f}): "
                    f"pulse={pulse:.3f} prior={prior:.3f} fw={factor_weight:.2f} "
                    f"score={score:.3f}"
                )
            if score > best_score:
                best_score = score
                best_bpm = cand

        if DEBUG and abs(best_bpm - raw_bpm) > 0.5:
            print(f"[LibrosaBeatDetector] Harmonic correction: {raw_bpm:.1f} -> {best_bpm:.1f} BPM")

        return best_bpm

    def _update_stabilized_bpm(self, new_bpm):
        """
        Update the reported BPM with hysteresis.

        Small deviations (<=3%) are fine-tracked with an EMA. Larger deviations
        must repeat for SWITCH_CONFIRM_READINGS consecutive passes (~2s each)
        before the tempo switches, preventing jumps from single bad readings.
        """
        # First lock
        if self.bpm <= 0:
            self.bpm = round(new_bpm, 1)
            self._pending_bpm = None
            self._pending_count = 0
            if DEBUG:
                print(f"[LibrosaBeatDetector] BPM locked: {self.bpm}")
            return

        deviation = abs(new_bpm - self.bpm) / self.bpm

        if deviation <= FINE_TRACK_TOLERANCE:
            # Fine tracking
            self.bpm = round(
                self.bpm * (1 - SMOOTHING_ALPHA) + new_bpm * SMOOTHING_ALPHA, 1
            )
            self._pending_bpm = None
            self._pending_count = 0
            if DEBUG:
                print(f"[LibrosaBeatDetector] BPM fine-tracked: {self.bpm}")
            return

        # Large deviation: count consecutive agreeing readings before switching
        if self._pending_bpm is not None and (
            abs(new_bpm - self._pending_bpm) / self._pending_bpm
            <= FINE_TRACK_TOLERANCE
        ):
            self._pending_count += 1
        else:
            self._pending_bpm = new_bpm
            self._pending_count = 1

        if self._pending_count >= SWITCH_CONFIRM_READINGS:
            print(f"[LibrosaBeatDetector] BPM change confirmed: {self.bpm} -> {new_bpm:.1f}")
            self.bpm = round(new_bpm, 1)
            self._pending_bpm = None
            self._pending_count = 0
        elif DEBUG:
            print(
                f"[LibrosaBeatDetector] Holding {self.bpm} BPM (candidate {new_bpm:.1f}, "
                f"{self._pending_count}/{SWITCH_CONFIRM_READINGS})"
            )

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
