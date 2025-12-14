#!/usr/bin/python
 
 
import pyaudio
import aubio
import numpy as np
from time import sleep
 
 
seconds = 10 # how long this script should run
 
bufferSize = 512
windowSizeMultiple = 2 # or 4 for higher accuracy, but more computational cost
 
audioInputDeviceIndex = 1 # use 'arecord -l' to check available audio devices
audioInputChannels = 1
 
 
# create the aubio tempo detection:
hopSize = bufferSize
winSize = hopSize * windowSizeMultiple
tempoDetection = aubio.tempo(method='default', buf_size=winSize, hop_size=hopSize, samplerate=audioInputSampleRate)
 
 
# this function gets called by the input stream, as soon as enough samples are collected from the audio input:
def readAudioFrames(in_data, frame_count, time_info, status):
 
    signal = np.frombuffer(in_data, dtype=np.float32)
 
    beat = tempoDetection(signal)
    if beat:
        bpm = tempoDetection.get_bpm()
        print("beat! (running with "+str(bpm)+" bpm)")
 
    return (in_data, pyaudio.paContinue)
 
 
# create and start the input stream
pa = pyaudio.PyAudio()
audioInputDevice = pa.get_device_info_by_index(audioInputDeviceIndex)
audioInputSampleRate = int(audioInputDevice['defaultSampleRate'])
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