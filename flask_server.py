from flask import Flask, render_template, Response
import zmq
import base64
import cv2
import numpy as np

app = Flask(__name__)

context = zmq.Context()
receiver = context.socket(zmq.PULL)
receiver.connect("tcp://localhost:5556")

def generate_frames():
    while True:
        jpg_base64 = receiver.recv()
        jpg_bytes = base64.b64decode(jpg_base64)
        np_arr = np.frombuffer(jpg_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        # 编码为 JPEG 并发送给前端
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
