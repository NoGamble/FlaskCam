from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import json
import zmq
import base64
import uuid
import time
import eventlet # 使用 eventlet 进行非阻塞 ZeroMQ 轮询

# 确保 eventlet 打补丁，以便与 SocketIO 协程兼容
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_random_key_here' # 请务必修改并保密！

# 使用 eventlet 的 SocketIO
socketio = SocketIO(app, async_mode='eventlet')

# 存储房间信息: { room_id: { username: sid, ... } }
rooms = {}
# 存储 sid 到用户名的映射: { sid: username }
sid_to_username = {}

# --- ZeroMQ 设置 (与分布式图片处理一致) ---
TASK_SEND_ADDRESS = "tcp://127.0.0.1:5555"
RESULT_RECEIVE_ADDRESS = "tcp://127.0.0.1:5556"

context = zmq.Context()

# ZeroMQ sockets (在 background task 中连接或在全局连接，这里选择全局连接)
task_sender = context.socket(zmq.PUSH)
task_sender.bind(TASK_SEND_ADDRESS) # Flask 绑定地址，worker 连接

result_receiver = context.socket(zmq.PULL)
result_receiver.bind(RESULT_RECEIVE_ADDRESS) # Flask 绑定地址，worker 连接

# 用于 ZeroMQ 接收的 Poller
poller = zmq.Poller()
poller.register(result_receiver, zmq.POLLIN)

# 用于追踪 ZeroMQ 任务结果应该发送给哪个客户端 SID
# { zmq_task_id: client_sid }
zmq_task_clients = {}

print("Flask app (Video Chat + Image Processing) started.")
print(f"ZeroMQ: Sending tasks to {TASK_SEND_ADDRESS}")
print(f"ZeroMQ: Receiving results from {RESULT_RECEIVE_ADDRESS}")
print("请确保 worker.py 进程已经启动!")

# --- SocketIO 事件处理 (视频聊天部分) ---
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def handle_join(data):
    room = data['room']
    username = data['username']
    sid = request.sid

    print(f"User {username} with SID {sid} joining room {room}")

    if room not in rooms:
        rooms[room] = {}

    if username in rooms[room]:
        print(f"Username {username} already exists in room {room}. Rejecting.")
        emit('join_error', {'message': 'Username already exists.'}, room=sid)
        return

    rooms[room][username] = sid
    sid_to_username[sid] = username
    join_room(room)

    current_users = list(rooms[room].keys())
    current_users.remove(username)

    print(f"Current users in room {room}: {list(rooms[room].keys())}")

    for user, user_sid in rooms[room].items():
        if user != username:
            emit('user_joined', {'username': username}, room=user_sid)
            print(f"Notified {user} (SID: {user_sid}) that {username} joined.")

    emit('users_in_room', {'users': current_users, 'room': room}, room=sid)
    print(f"Sent current users {current_users} to new user {username} (SID: {sid}) in room {room}.")


@socketio.on('leave')
def handle_leave(data):
    room = data.get('room')
    username = data.get('username')
    sid = request.sid

    if room and username and room in rooms and username in rooms[room] and rooms[room][username] == sid:
        print(f"User {username} with SID {sid} leaving room {room}")

        leave_room(room)
        del rooms[room][username]
        del sid_to_username[sid]

        if not rooms[room]:
            del rooms[room]
            print(f"Room {room} is now empty and removed.")

        emit('user_left', {'username': username, 'room': room}, room=room)
        print(f"Notified users in room {room} that {username} left.")
    else:
        print(f"Leave request failed for SID {sid}. Data: {data}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    username = sid_to_username.get(sid)

    if username:
        print(f"User {username} with SID {sid} disconnected.")
        room_to_leave = None
        for room_id, users_in_room in rooms.items():
            if username in users_in_room and users_in_room[username] == sid:
                room_to_leave = room_id
                break

        if room_to_leave:
            handle_leave({'room': room_to_leave, 'username': username})

        # 清理可能关联到此 SID 的待处理 ZeroMQ 任务 (简单清理)
        # 更好的方法是在 worker 中实现心跳和任务取消
        tasks_to_remove = [task_id for task_id, client_sid in zmq_task_clients.items() if client_sid == sid]
        for task_id in tasks_to_remove:
             del zmq_task_clients[task_id]
             print(f"Cleaned up pending ZeroMQ task {task_id} for disconnected SID {sid}")

    else:
         print(f"Unknown SID {sid} disconnected.")

@socketio.on('offer')
def handle_offer(data):
    forward_signal('offer', data)

@socketio.on('answer')
def handle_answer(data):
    forward_signal('answer', data)

@socketio.on('candidate')
def handle_candidate(data):
    forward_signal('candidate', data)

# Helper to forward WebRTC signals
def forward_signal(event_name, data):
    room = data.get('room')
    target_username = data.get('to_username')
    from_username = data.get('from_username')
    signal_payload = data.get(event_name)

    if room and target_username and from_username and room in rooms:
        target_sid = rooms[room].get(target_username)
        if target_sid:
            payload_to_send = {
                'room': room,
                'from_username': from_username,
                event_name: signal_payload
            }
            emit(event_name, payload_to_send, room=target_sid)
            # print(f"Forwarding {event_name} from {from_username} to {target_username} (SID: {target_sid}) in room {room}.")
        # else: print message if target_sid not found


@socketio.on('process_snapshot')
def handle_process_snapshot(data):
    """处理客户端的快照请求，并发送到 ZeroMQ 队列"""
    client_sid = request.sid
    image_data_url = data.get('image_data_url')  # Base64 数据
    effect_type = data.get('effect')

    if not image_data_url or not effect_type:
        print(f"Invalid snapshot request from SID {client_sid}")
        return

    # 提取 Base64 数据部分
    try:
        header, base64_data = image_data_url.split(',', 1)
        image_bytes = base64.b64decode(base64_data)
    except Exception as e:
        print(f"Error decoding base64 image data from SID {client_sid}: {e}")
        emit('snapshot_processed', {'status': 'error', 'message': 'Invalid image data'}, room=client_sid)
        return

    # 生成任务 ID
    task_id = str(uuid.uuid4())

    # 存储任务 ID 与客户端 SID 的映射
    zmq_task_clients[task_id] = client_sid
    print(f"Received snapshot task {task_id} for effect '{effect_type}' from SID {client_sid}")

    # 构建 ZeroMQ 任务消息
    task_message = {
        'task_id': task_id,
        'effect': effect_type,
        'image_data': base64_data  # 发送 Base64 编码后的数据
    }

    try:
        # 发送任务到 ZeroMQ 队列
        task_sender.send_string(json.dumps(task_message))
        print(f"Sent ZeroMQ task {task_id}")

        # 发送给客户端反馈，表示任务已接收并处理中
        emit('snapshot_processing', {'task_id': task_id, 'status': 'received'}, room=client_sid)

    except Exception as e:
        print(f"Error sending ZeroMQ task {task_id}: {e}")
        if task_id in zmq_task_clients:
             del zmq_task_clients[task_id]
        emit('snapshot_processed', {'task_id': task_id, 'status': 'error', 'message': 'Failed to send task to worker'}, room=client_sid)



def zmq_result_poller_task():
    """后台任务，持续轮询 ZeroMQ 结果"""
    print("ZeroMQ result poller background task started.")
    while True:
        # 非阻塞轮询 ZeroMQ
        sockets = dict(poller.poll(timeout=100))  # 100ms 超时

        if result_receiver in sockets and sockets[result_receiver] == zmq.POLLIN:
            try:
                result_message_str = result_receiver.recv_string(zmq.NOBLOCK)
                result_message = json.loads(result_message_str)

                task_id = result_message.get('task_id')
                status = result_message.get('status')
                processed_image_base64 = result_message.get('processed_image_data')
                error_message = result_message.get('message')

                print(f"Received ZeroMQ result for task {task_id} with status: {status}")

                # 查找客户端 SID
                client_sid = zmq_task_clients.pop(task_id, None)  # 结果收到后就从字典中移除

                if client_sid:
                    # 获取房间ID
                    room = None
                    for room_id, users in rooms.items():
                        if client_sid in users.values():
                            room = room_id
                            break

                    # 向房间内的所有用户广播结果
                    if room:
                        # 如果图像处理成功，广播给所有用户
                        if status == 'completed' and processed_image_base64:
                            socketio.emit('snapshot_processed', {
                                'task_id': task_id,
                                'status': 'completed',
                                'image_data_url': f"data:image/png;base64,{processed_image_base64}"
                            }, room=room)
                            print(f"Broadcasted processed snapshot result for task {task_id} to room {room}")

                        else:  # 处理失败，广播错误信息
                            socketio.emit('snapshot_processed', {
                                'task_id': task_id,
                                'status': 'error',
                                'message': error_message if error_message else 'Unknown processing error'
                            }, room=room)
                            print(f"Broadcasted error result for task {task_id} to room {room}")

            except zmq.Again:
                pass  # 没有消息
            except Exception as e:
                print(f"Error in ZeroMQ result poller task: {e}")

        eventlet.sleep(0.01)  # 使用 eventlet 的 sleep，避免 CPU 占用过高


# 在 SocketIO 启动时，启动 ZeroMQ 结果轮询后台任务
@socketio.on('connect')
def handle_connect(auth):
    print(f"Client connected: {request.sid}")
    # 确保 ZeroMQ 轮询任务已经启动
    # 理想情况下，这个任务只启动一次。可以在 if __name__ == '__main__': 中启动
    # 这里的 connect handler 只是确保连接上 SocketIO 的客户端能被后面的 Poller 找到
    # 启动 background task 应该在 run() 之前或之后一次性完成

# ZeroMQ cleanup on exit
import atexit
@atexit.register
def cleanup_zmq():
    print("Cleaning up ZeroMQ sockets.")
    task_sender.close()
    result_receiver.close()
    context.term()
    print("ZeroMQ cleanup complete.")

# 确保 ZeroMQ 轮询任务在 SocketIO 服务器启动时启动一次
def start_zmq_poller():
    socketio.start_background_task(target=zmq_result_poller_task)
    print("ZeroMQ result poller background task scheduled.")


if __name__ == '__main__':
    # ... (保持原有 main 部分，确保 start_zmq_poller() 在 socketio.run() 之前被调用一次) ...
    start_zmq_poller()
    print("Starting SocketIO server...")
    socketio.run(app, debug=True, host='127.0.0.1', port=5000, use_reloader=False)