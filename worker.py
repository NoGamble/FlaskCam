import zmq
import time
import cv2
import numpy as np
import json
import base64
import math
import socket

def get_local_ip():
    """获取本机局域网IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

# 使用本机IP地址
LOCAL_IP = get_local_ip()

# ZeroMQ 设置 - 使用动态IP
TASK_RECEIVE_ADDRESS = f"tcp://{LOCAL_IP}:5555"  # 连接到Flask的发送地址
RESULT_SEND_ADDRESS = f"tcp://{LOCAL_IP}:5556"   # 连接到Flask的接收地址

context = zmq.Context()

# 设置socket选项避免地址占用
def create_socket(socket_type, address, bind=False):
    sock = context.socket(socket_type)
    sock.setsockopt(zmq.LINGER, 0)  # 关闭时立即释放资源
    sock.setsockopt(zmq.RCVTIMEO, 1000)  # 接收超时1秒
    sock.setsockopt(zmq.SNDTIMEO, 1000)  # 发送超时1秒
    if bind:
        sock.bind(address)
    else:
        sock.connect(address)
    return sock

print(f"Worker started on {LOCAL_IP}")
print(f"Receiving tasks from {TASK_RECEIVE_ADDRESS}")
print(f"Sending results to {RESULT_SEND_ADDRESS}")

try:
    # 接收任务的socket (PULL模式)
    task_receiver = create_socket(zmq.PULL, TASK_RECEIVE_ADDRESS)
    
    # 发送结果的socket (PUSH模式)
    result_sender = create_socket(zmq.PUSH, RESULT_SEND_ADDRESS)
    
    # 设置轮询器
    poller = zmq.Poller()
    poller.register(task_receiver, zmq.POLLIN)
except zmq.ZMQError as e:
    print(f"ZeroMQ初始化失败: {e}")
    exit(1)

# --- 特效处理函数 (优化版) ---

def enlarge_effect(img):
    """优化后的哈哈镜放大效果"""
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    radius = min(w, h) // 3  # 动态半径
    
    # 使用numpy向量化操作提高性能
    y, x = np.indices((h, w))
    tx = x - cx
    ty = y - cy
    dist_sq = tx**2 + ty**2
    
    mask = dist_sq < radius**2
    dist = np.sqrt(dist_sq[mask])
    scale = dist / (radius / 2)
    
    srcX = np.clip((tx[mask] / 2 * scale + cx).astype(int), 0, w-1)
    srcY = np.clip((ty[mask] / 2 * scale + cy).astype(int), 0, h-1)
    
    result = img.copy()
    result[y[mask], x[mask]] = img[srcY, srcX]
    return result

def reduce_effect(img):
    """优化后的哈哈镜缩小效果"""
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    
    h, w = img.shape[:2]
    cx, cy = w / 2, h / 2
    radius = min(h, w) / 3.0
    compress_factor = 0.8
    
    # 向量化计算
    y, x = np.indices((h, w))
    tx = x - cx
    ty = y - cy
    distance = np.sqrt(tx**2 + ty**2)
    angle = np.arctan2(ty, tx)
    
    mask = distance > 0
    dist_src = np.power(distance[mask], compress_factor) * radius / np.power(radius, compress_factor)
    
    srcX = np.clip((cx + dist_src * np.cos(angle[mask])).astype(int), 0, w-1)
    srcY = np.clip((cy + dist_src * np.sin(angle[mask])).astype(int), 0, h-1)
    
    result = img.copy()
    result[y[mask], x[mask]] = img[srcY, srcX]
    return result

def blur_effect(img):
    """高斯模糊效果"""
    return cv2.GaussianBlur(img, (15, 15), 0)

def edge_detection_effect(img):
    """边缘检测效果"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

EFFECT_FUNCTIONS = {
    'enlarge': enlarge_effect,
    'reduce': reduce_effect,
    'blur': blur_effect,
    'edge_detection': edge_detection_effect
}

def process_image_task(task_message):
    """处理单个图片任务"""
    task_id = task_message.get('task_id')
    effect_type = task_message.get('effect')
    image_data_base64 = task_message.get('image_data')
    
    if not all([task_id, effect_type, image_data_base64]):
        return {
            'task_id': task_id,
            'status': 'error',
            'message': 'Invalid task format'
        }
    
    try:
        # 解码图片
        image_bytes = base64.b64decode(image_data_base64)
        img_np = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img_np is None:
            raise ValueError("Failed to decode image")
        
        # 应用特效
        if effect_type not in EFFECT_FUNCTIONS:
            raise ValueError(f"Unknown effect type: {effect_type}")
        
        start_time = time.time()
        processed_img = EFFECT_FUNCTIONS[effect_type](img_np)
        processing_time = time.time() - start_time
        
        # 编码结果
        success, encoded_img = cv2.imencode('.png', processed_img)
        if not success:
            raise ValueError("Failed to encode processed image")
        
        return {
            'task_id': task_id,
            'status': 'completed',
            'processing_time': processing_time,
            'processed_image_data': base64.b64encode(encoded_img).decode('utf-8')
        }
        
    except Exception as e:
        return {
            'task_id': task_id,
            'status': 'error',
            'message': str(e)
        }

# --- Worker主循环 ---
def worker_loop():
    while True:
        try:
            # 非阻塞接收任务
            socks = dict(poller.poll(100))  # 100ms超时
            
            if task_receiver in socks:
                task_message_str = task_receiver.recv_string()
                task_message = json.loads(task_message_str)
                
                print(f"Processing task {task_message.get('task_id')}")
                
                # 处理任务
                result = process_image_task(task_message)
                
                # 发送结果
                result_sender.send_string(json.dumps(result))
                print(f"Completed task {result['task_id']} with status {result['status']}")
                
        except zmq.Again:
            continue  # 无任务到达，继续轮询
        except zmq.ZMQError as e:
            print(f"ZeroMQ error: {e}")
            time.sleep(1)  # 短暂等待后重试
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(1)

def cleanup():
    """清理资源"""
    print("\nCleaning up resources...")
    poller.unregister(task_receiver)
    task_receiver.close()
    result_sender.close()
    context.term()
    print("Cleanup complete.")

if __name__ == '__main__':
    import atexit
    atexit.register(cleanup)
    
    try:
        print("Worker started. Press Ctrl+C to exit.")
        worker_loop()
    except KeyboardInterrupt:
        print("\nWorker stopped by user")
    finally:
        cleanup()