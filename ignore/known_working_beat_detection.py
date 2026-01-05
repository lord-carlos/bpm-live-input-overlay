#!/usr/bin/python
 
 
import pyaudio
import aubio
import numpy as np
from time import sleep
 
 
seconds = 20 # how long this script should run
 
bufferSize = 64
windowSizeMultiple = 32 # Keep window size large (2048) for bass, but small hop for timing
 
audioInputDeviceIndex = 2 # use 'arecord -l' to check available audio devices
audioInputChannels = 1

# Force a standard sample rate to avoid clock drift issues on Windows
audioInputSampleRate = 44100

# Calibration factor to correct systematic BPM offset (122 / 122.32)
BPM_CALIBRATION = 0.9974
 
 
# create and start the input stream
pa = pyaudio.PyAudio()
# We no longer query the device for sample rate; we use our forced rate above

# create the aubio tempo detection:
hopSize = bufferSize
winSize = hopSize * windowSizeMultiple
# Revert to 'default' method, smaller hop size improves timing accuracy
tempoDetection = aubio.tempo(method='default', buf_size=winSize, hop_size=hopSize, samplerate=audioInputSampleRate)
# Set a threshold to avoid false positives (doubling)
tempoDetection.set_threshold(0.5)
 
 
# this function gets called by the input stream, as soon as enough samples are collected from the audio input:
def readAudioFrames(in_data, frame_count, time_info, status):
 
    signal = np.frombuffer(in_data, dtype=np.float32)
 
    beat = tempoDetection(signal)
    if beat:
        raw_bpm = tempoDetection.get_bpm()
        bpm = raw_bpm * BPM_CALIBRATION
        print("beat! (running with "+str(bpm)+" bpm)")
 
    return (in_data, pyaudio.paContinue)
 
inputStream = pa.open(format=pyaudio.paFloat32,
                input=True,
                channels=audioInputChannels,
                input_device_index=audioInputDeviceIndex,
                frames_per_buffer=bufferSize,
                rate=audioInputSampleRate,
                stream_callback=readAudioFrames)
 
# because the input stream runs asynchronously, we just wait for a few seconds here before stopping the script:
sleep(seconds)
 
inputStream.stop_stream()
inputStream.close()
pa.terminate()