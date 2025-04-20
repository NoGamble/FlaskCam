import zmq
import cv2
import pyaudio

# ZeroMQ设置
context = zmq.Context()
socket_video = context.socket(zmq.PUB)
socket_audio = context.socket(zmq.PUB)
socket_video.bind("tcp://127.0.0.1:5555")  # 发布视频流
socket_audio.bind("tcp://127.0.0.1:5556")  # 发布音频流

# 打开摄像头
cap = cv2.VideoCapture(0)

# PyAudio设置
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 1024

# 打开音频流
audio = pyaudio.PyAudio()
stream = audio.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

while True:
    # 获取视频流
    ret, frame = cap.read()
    if not ret:
        break
    ret, buffer = cv2.imencode('.jpg', frame)
    frame_data = buffer.tobytes()
    socket_video.send(frame_data)  # 发布视频流

    # 获取音频流
    audio_data = stream.read(CHUNK)
    socket_audio.send(audio_data)  # 发布音频流

cap.release()
