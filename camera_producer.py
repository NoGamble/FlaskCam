import zmq
import cv2
import base64

context = zmq.Context()
socket = context.socket(zmq.PUSH)
socket.bind("tcp://*:5555")

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        continue
    _, buffer = cv2.imencode('.jpg', frame)
    jpg_base64 = base64.b64encode(buffer)
    socket.send(jpg_base64)
