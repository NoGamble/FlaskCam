import zmq
import cv2
import numpy as np
import base64

context = zmq.Context()
receiver = context.socket(zmq.PULL)
receiver.connect("tcp://localhost:5555")

sender = context.socket(zmq.PUSH)
sender.bind("tcp://*:5556")

while True:
    jpg_base64 = receiver.recv()
    jpg_bytes = base64.b64decode(jpg_base64)
    np_img = np.frombuffer(jpg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    # 图像处理：灰度化
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, buffer = cv2.imencode('.jpg', gray)
    jpg_result = base64.b64encode(buffer)

    sender.send(jpg_result)
