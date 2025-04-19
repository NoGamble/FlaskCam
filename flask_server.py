from flask import Flask, render_template, send_file
import zmq
import base64

import os

app = Flask(__name__)

context = zmq.Context()
receiver = context.socket(zmq.PULL)
receiver.connect("tcp://localhost:5556")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/image')
def image():
    jpg_base64 = receiver.recv()
    with open("static/latest.jpg", "wb") as f:
        f.write(base64.b64decode(jpg_base64))
    return send_file("static/latest.jpg", mimetype='image/jpeg')

if __name__ == '__main__':
    os.makedirs("static", exist_ok=True)
    with open("static/latest.jpg", "wb") as f:
        f.write(b"")  
    app.run(host='0.0.0.0', port=5001, debug=True)

