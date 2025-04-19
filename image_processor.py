import zmq

context = zmq.Context()
receiver = context.socket(zmq.PULL)
receiver.connect("tcp://localhost:5555")

sender = context.socket(zmq.PUSH)
sender.bind("tcp://*:5556")

while True:
    jpg_base64 = receiver.recv()
    sender.send(jpg_base64)
