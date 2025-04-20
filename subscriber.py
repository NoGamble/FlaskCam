import zmq
import cv2
import numpy as np
import pyaudio

# ZeroMQ设置
context = zmq.Context()
socket_video = context.socket(zmq.SUB)
socket_audio = context.socket(zmq.SUB)

socket_video.connect("tcp://127.0.0.1:5555")  # 订阅视频流
socket_audio.connect("tcp://127.0.0.1:5556")  # 订阅音频流
socket_video.setsockopt_string(zmq.SUBSCRIBE, "")
socket_audio.setsockopt_string(zmq.SUBSCRIBE, "")

# PyAudio设置
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 1024

# 打开音频流播放
audio = pyaudio.PyAudio()
stream = audio.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    output=True,
                    frames_per_buffer=CHUNK)

while True:
    # 接收视频数据
    frame_data = socket_video.recv()
    nparr = np.frombuffer(frame_data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    cv2.imshow('Received Video', frame)

    # 接收音频数据并播放
    audio_data = socket_audio.recv()
    stream.write(audio_data)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
