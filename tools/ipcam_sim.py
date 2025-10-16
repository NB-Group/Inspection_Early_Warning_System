"""
本地IP摄像头模拟服务器

功能：
- 将本机多个摄像头（按索引）映射为 MJPEG HTTP 流：/cam/<index>
- 提供单帧抓拍：/shot/<index>
- 提供连续音频WAV流：/audio.wav（白噪声），用于分贝阈值测试

用法：
  python tools/ipcam_sim.py --cams 0 1 --port 8090 --fps 20

然后在应用配置中：
- 前置URL： http://127.0.0.1:8090/cam/0
- 后置URL： http://127.0.0.1:8090/cam/1
- 音频URL： http://127.0.0.1:8090/audio.wav

注意：
- 需要 opencv-python
- 运行时请保持终端开启
"""

import argparse
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import cv2
import numpy as np


class CameraWorker:
    def __init__(self, index: int, fps: int = 20):
        self.index = index
        self.fps = fps
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.cap = cv2.VideoCapture(self.index)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开本地摄像头 {self.index}")
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(f"本地摄像头 {self.index} 已启动")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        print(f"本地摄像头 {self.index} 已停止")

    def _loop(self):
        interval = 1.0 / max(1, self.fps)
        while self.running:
            try:
                ok, frame = self.cap.read()
                if ok:
                    with self.lock:
                        self.frame = frame
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"摄像头{self.index} 读取错误: {e}")
                time.sleep(0.2)
            time.sleep(interval)

    def get_jpeg(self, quality: int = 80):
        with self.lock:
            if self.frame is None:
                return None
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            ok, buf = cv2.imencode('.jpg', self.frame, encode_param)
            if not ok:
                return None
            return buf.tobytes()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MJPEGHandler(BaseHTTPRequestHandler):
    server_version = "IPCamSim/1.0"

    def do_GET(self):
        try:
            if self.path.startswith('/cam/'):
                return self.handle_mjpeg()
            if self.path.startswith('/shot/'):
                return self.handle_shot()
            if self.path.startswith('/audio.wav'):
                return self.handle_audio()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"IPCamSim running. Endpoints: /cam/<idx>, /shot/<idx>, /audio.wav")
        except Exception as e:
            try:
                self.send_error(500, f"Server error: {e}")
            except Exception:
                pass

    def handle_mjpeg(self):
        parts = self.path.split('/')
        if len(parts) < 3:
            self.send_error(404, 'Camera index required')
            return
        idx_str = parts[2]
        try:
            cam_idx = int(idx_str)
        except ValueError:
            self.send_error(400, 'Invalid camera index')
            return
        cam = self.server.cameras.get(cam_idx)
        if not cam:
            self.send_error(404, 'Camera not configured')
            return
        boundary = 'frame'
        self.send_response(200)
        self.send_header('Age', 0)
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Content-Type', f'multipart/x-mixed-replace; boundary={boundary}')
        self.end_headers()
        try:
            while True:
                jpg = cam.get_jpeg()
                if jpg is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(bytes(f"--{boundary}\r\n", 'utf-8'))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(bytes(f"Content-Length: {len(jpg)}\r\n\r\n", 'utf-8'))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                # 控制帧间隔
                time.sleep(self.server.interval)
        except Exception:
            # 客户端断开
            pass

    def handle_shot(self):
        parts = self.path.split('/')
        if len(parts) < 3:
            self.send_error(404, 'Camera index required')
            return
        idx_str = parts[2]
        try:
            cam_idx = int(idx_str)
        except ValueError:
            self.send_error(400, 'Invalid camera index')
            return
        cam = self.server.cameras.get(cam_idx)
        if not cam:
            self.send_error(404, 'Camera not configured')
            return
        jpg = cam.get_jpeg()
        if jpg is None:
            self.send_error(503, 'Frame not available')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(jpg)))
        self.end_headers()
        self.wfile.write(jpg)

    def handle_audio(self):
        # 生成白噪声WAV流（16kHz, 16bit mono）
        sample_rate = 16000
        bits = 16
        channels = 1
        chunk_ms = 200
        bytes_per_sample = bits // 8
        block_align = channels * bytes_per_sample
        byte_rate = sample_rate * block_align
        # 写入WAV头（data大小不准确，但用于流式读取足够）
        def wav_header():
            buf = io.BytesIO()
            # RIFF header
            buf.write(b'RIFF')
            buf.write((0xffffffff).to_bytes(4, 'little', signed=False))
            buf.write(b'WAVE')
            # fmt chunk
            buf.write(b'fmt ')
            buf.write((16).to_bytes(4, 'little'))  # PCM
            buf.write((1).to_bytes(2, 'little'))   # PCM format
            buf.write((channels).to_bytes(2, 'little'))
            buf.write((sample_rate).to_bytes(4, 'little'))
            buf.write((byte_rate).to_bytes(4, 'little'))
            buf.write((block_align).to_bytes(2, 'little'))
            buf.write((bits).to_bytes(2, 'little'))
            # data chunk
            buf.write(b'data')
            buf.write((0xffffffff).to_bytes(4, 'little', signed=False))
            return buf.getvalue()

        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        # 逐块发送白噪声
        try:
            self.wfile.write(wav_header())
            chunk_samples = int(sample_rate * (chunk_ms / 1000.0))
            while True:
                noise = (np.random.rand(chunk_samples) * 2 - 1.0)  # [-1,1)
                pcm16 = (noise * 32767.0).astype(np.int16).tobytes()
                self.wfile.write(pcm16)
                time.sleep(chunk_ms / 1000.0)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cams', nargs='+', type=int, default=[0], help='本地摄像头索引列表，如 0 1')
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--fps', type=int, default=20)
    args = parser.parse_args()

    # 启动摄像头采集
    cameras = {}
    workers = []
    for idx in args.cams:
        worker = CameraWorker(idx, fps=args.fps)
        worker.start()
        workers.append(worker)
        cameras[idx] = worker

    class _Server(ThreadingHTTPServer):
        pass

    server = _Server(('0.0.0.0', args.port), MJPEGHandler)
    server.cameras = cameras
    server.interval = 1.0 / max(1, args.fps)
    print(f"IPCamSim 已启动：http://127.0.0.1:{args.port}  (cams: {args.cams})")
    print("Endpoints: /cam/<idx> (MJPEG), /shot/<idx> (JPEG), /audio.wav (WAV stream)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for w in workers:
            w.stop()


if __name__ == '__main__':
    main()


