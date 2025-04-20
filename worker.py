import zmq
import time
import cv2
import numpy as np
import json
import base64
import math

# ZeroMQ 设置
TASK_RECEIVE_ADDRESS = "tcp://127.0.0.1:5555" # 连接到 Flask 绑定的发送任务地址
RESULT_SEND_ADDRESS = "tcp://127.0.0.1:5556"   # 连接到 Flask 绑定的接收结果地址

context = zmq.Context()

# 用于接收任务的 socket (PULL 模式)
task_receiver = context.socket(zmq.PULL)
task_receiver.connect(TASK_RECEIVE_ADDRESS)

# 用于发送结果的 socket (PUSH 模式)
result_sender = context.socket(zmq.PUSH)
result_sender.connect(RESULT_SEND_ADDRESS)

print("Worker started. Connecting to ZeroMQ addresses.")
print(f"Receiving tasks from {TASK_RECEIVE_ADDRESS}")
print(f"Sending results to {RESULT_SEND_ADDRESS}")

# --- 特效处理函数 (与之前的相同) ---

# 哈哈镜放大效果 (恢复到用户最初的版本逻辑)
def enlarge_effect(img):
    # 确保图片是彩色的，如果边缘检测等返回灰度图，这里需要转换
    if len(img.shape) == 2:
         img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    h, w, n = img.shape
    cx = w // 2 # 使用 // 进行整数除法
    cy = h // 2 # 使用 // 进行整数除法

    # 恢复用户最初版本中的固定半径和 r 计算
    # 注意：这个固定值可能导致在不同尺寸图片上效果区域大小不同
    radius = 100
    r = int(radius / 2.0) # r = 50

    new_img = img.copy()

    # 像素遍历和映射 (使用标准的 y, x 循环顺序)
    for y in range(h): # 外层循环是行 (y)
        for x in range(w): # 内层循环是列 (x)
            tx = x - cx # 当前像素点相对于中心的 x 偏移
            ty = y - cy # 当前像素点相对于中心的 y 偏移

            # 恢复用户最初代码中计算距离的方式 (实际上是距离的平方)
            # 用户代码中的 'distance' 变量实际上是 squared_distance
            dist_sq_original_var_name = tx * tx + ty * ty

            # 恢复用户最初代码中的圆内判断，使用 squared_distance 和 radius * radius
            if dist_sq_original_var_name < radius * radius:
                # 恢复用户最初代码中计算原像素坐标的公式
                # 公式中使用的是 math.sqrt(distance) / r，这里的 'distance' 是上面的 squared_distance
                # 也就是说，计算的是 真实距离 / r 作为缩放因子
                dist = math.sqrt(dist_sq_original_var_name) # 真实距离

                # 恢复用户最初代码中的计算结构
                # int(int(tx / 2.0) * (dist / r) + cx)
                # 需要确保 r 不为零
                scale_factor = (dist / r) if r != 0 else 0

                # 复制用户最初代码中的类型转换和计算顺序
                srcX = int(int(tx / 2.0) * scale_factor + cx)
                srcY = int(int(ty / 2.0) * scale_factor + cy)

                # 边界检查 (与原代码逻辑一致，只在原坐标有效时复制像素)
                if 0 <= srcX < w and 0 <= srcY < h:
                    new_img[y, x] = img[srcY, srcX]
                # 原代码没有 else，不在范围内的像素保持原样 (因为是 copy)

    return new_img

# 哈哈镜缩小效果
def reduce_effect(img):
    if len(img.shape) == 2:
         img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w, n = img.shape
    cx = w / 2
    cy = h / 2
    radius = min(h, w) / 3.0
    compress_factor = 0.8
    new_img = img.copy()
    for y in range(h):
        for x in range(w):
            tx = x - cx
            ty = y - cy
            distance = math.sqrt(tx * tx + ty * ty)
            angle = math.atan2(ty, tx)
            dist_src = math.pow(distance, compress_factor) * radius/math.pow(radius,compress_factor)
            srcX = int(cx + dist_src * math.cos(angle))
            srcY = int(cy + dist_src * math.sin(angle))
            if 0 <= srcX < w and 0 <= srcY < h:
                 new_img[y, x] = img[srcY, srcX]
    return new_img

# 图像模糊效果
def blur_effect(img):
    return cv2.GaussianBlur(img, (15, 15), 0)

# 边缘检测效果
def edge_detection_effect(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

# 特效函数映射
EFFECT_FUNCTIONS = {
    'enlarge': enlarge_effect,
    'reduce': reduce_effect,
    'blur': blur_effect,
    'edge_detection': edge_detection_effect
}

# --- Worker 主循环 ---
while True:
    # print("Worker: Waiting for task...")
    try:
        # 接收任务消息 (这里是阻塞接收，worker 空闲时会在这里等待)
        task_message_str = task_receiver.recv_string()
        task_message = json.loads(task_message_str)

        task_id = task_message.get('task_id')
        effect_type = task_message.get('effect')
        image_data_base64 = task_message.get('image_data')

        if not all([task_id, effect_type, image_data_base64]):
            print(f"Worker: Invalid task received: {task_message}")
            # 可以考虑发送一个错误结果
            continue

        print(f"Worker: Received task {task_id} for effect '{effect_type}'")

        # 解码图片数据
        img_np = None
        error_message = None
        try:
            image_bytes = base64.b64decode(image_data_base64)
            img_np = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img_np is None:
                 error_message = "Failed to decode image"
                 print(f"Worker: {error_message} for task {task_id}")

        except Exception as e:
             error_message = f"Image decoding error: {e}"
             print(f"Worker: {error_message} for task {task_id}")


        # 执行特效处理
        processed_img_np = None
        if img_np is not None and error_message is None:
            if effect_type in EFFECT_FUNCTIONS:
                try:
                    start_time = time.time()
                    processed_img_np = EFFECT_FUNCTIONS[effect_type](img_np)
                    end_time = time.time()
                    print(f"Worker: Processed task {task_id} ({effect_type}) in {end_time - start_time:.4f} seconds")

                except Exception as e:
                    error_message = f"Effect processing error: {e}"
                    print(f"Worker: {error_message} for task {task_id}: {e}")
            else:
                error_message = f"Unknown effect type: {effect_type}"
                print(f"Worker: {error_message} for task {task_id}")

        # 编码处理后的图片并发送结果
        result_message = {'task_id': task_id}
        if processed_img_np is not None and error_message is None:
            try:
                success, encoded_image = cv2.imencode('.png', processed_img_np) # 编码为 PNG

                if success:
                    processed_image_base64 = base64.b64encode(encoded_image).decode('utf-8')
                    result_message['status'] = 'completed'
                    result_message['processed_image_data'] = processed_image_base64
                    print(f"Worker: Encoded and ready to send result for task {task_id}")
                else:
                    error_message = "Failed to encode processed image"
                    print(f"Worker: {error_message} for task {task_id}")

            except Exception as e:
                 error_message = f"Image encoding error: {e}"
                 print(f"Worker: {error_message} for task {task_id}")


        if error_message:
            result_message['status'] = 'error'
            result_message['message'] = error_message
            print(f"Worker: Sending error result for task {task_id}: {error_message}")


        # 发送结果到 Flask
        result_sender.send_string(json.dumps(result_message))
        print(f"Worker: Result for task {task_id} sent.")


    except zmq.Again:
        # Non-blocking receive would raise this, but worker is blocking PULL
        pass
    except Exception as e:
        # 捕获 ZeroMQ 接收过程中的异常
        print(f"Worker: Error in main loop: {e}")
        time.sleep(1) # 遇到错误稍作等待，避免无限循环或CPU过高

# 清理 ZeroMQ 上下文
def cleanup_zmq_worker():
    print("Worker: Cleaning up ZeroMQ sockets.")
    task_receiver.close()
    result_sender.close()
    context.term()
    print("Worker: ZeroMQ cleanup complete.")

import atexit
atexit.register(cleanup_zmq_worker)