"""
摄像头监控模块
"""

import cv2
import numpy as np
import threading
import time
from typing import Optional, Callable
import base64


class CameraMonitor:
    """摄像头监控器（支持本地摄像头与IP摄像头）"""
    
    def __init__(self, camera_index: int = 0, camera_type: str = "local", stream_url: str = ""):
        self.camera_type = camera_type  # 'local' or 'ip'
        self.camera_index = camera_index
        self.stream_url = stream_url
        self.camera = None
        self.running = False
        self.thread = None
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.callbacks = []
        self._consecutive_failures = 0
        # 录制相关
        self.recording = False
        self.video_writer = None
        self.record_lock = threading.Lock()
        self.record_path = None
    
    def start(self):
        """启动摄像头"""
        if self.running:
            return
        
        self._open_camera()
        
        if not self.camera or not self.camera.isOpened():
            src_desc = self.stream_url if self.camera_type == 'ip' else str(self.camera_index)
            raise RuntimeError(f"无法打开摄像头源: {src_desc}")
        
        # 尝试设置参数（并非所有源都支持）
        try:
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
        except Exception:
            pass
        
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        
        src_desc = self.stream_url if self.camera_type == 'ip' else str(self.camera_index)
        print(f"摄像头源已启动: {src_desc}")
    
    def stop(self):
        """停止摄像头"""
        if self.running or self.camera:
            self.running = False
            
            if self.thread:
                self.thread.join(timeout=2.0)
            
            if self.camera:
                self.camera.release()
                self.camera = None
            
            print("摄像头已停止")
        # 如果本来就没在运行，不打印任何消息
    
    def _capture_loop(self):
        """摄像头捕获循环"""
        while self.running:
            try:
                ret, frame = self.camera.read()
                
                if ret:
                    self._consecutive_failures = 0
                    with self.frame_lock:
                        self.current_frame = frame.copy()
                    
                    # 写入录像
                    if self.recording and self.video_writer is not None:
                        try:
                            with self.record_lock:
                                self.video_writer.write(frame)
                        except Exception as e:
                            print(f"录像写入失败: {e}")
                    
                    # 调用所有回调函数
                    for callback in self.callbacks:
                        try:
                            callback(frame)
                        except Exception as e:
                            print(f"回调函数执行错误: {e}")
                else:
                    print("读取摄像头帧失败")
                    self._consecutive_failures += 1
                    # 连续失败太多，尝试重连
                    if self._consecutive_failures >= 30:
                        print("尝试重连摄像头源...")
                        self._reopen_camera()
                        self._consecutive_failures = 0
                    time.sleep(0.1)
                
                # 控制帧率
                time.sleep(0.033)  # ~30fps
                
            except Exception as e:
                print(f"摄像头捕获错误: {e}")
                time.sleep(0.1)

    def start_recording(self, file_path: str, fps: int = 25):
        """开始录制视频到指定文件。"""
        if not self.is_running():
            raise RuntimeError("摄像头未运行，无法开始录制")
        with self.record_lock:
            if self.recording:
                return self.record_path
            # 获取帧大小
            frame = self.get_frame()
            if frame is None:
                raise RuntimeError("无法获取当前帧以初始化录制")
            height, width = frame.shape[:2]
            # 选择编码器MP4V，保存为mp4
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(file_path, fourcc, fps, (width, height))
            if not self.video_writer.isOpened():
                self.video_writer = None
                raise RuntimeError("无法打开视频文件进行写入")
            self.recording = True
            self.record_path = file_path
            print(f"开始录制: {file_path}")
            return file_path

    def stop_recording(self):
        """停止录制并释放资源。"""
        with self.record_lock:
            if self.video_writer is not None:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
                self.video_writer = None
            if self.recording:
                print(f"结束录制: {self.record_path}")
            self.recording = False
            path = self.record_path
            self.record_path = None
            return path

    def _open_camera(self):
        """打开摄像头源"""
        try:
            if self.camera:
                try:
                    self.camera.release()
                except Exception:
                    pass
                self.camera = None
            if self.camera_type == 'ip' and self.stream_url:
                # 支持HTTP(MJPEG)/RTSP/FILE等OpenCV可识别的URL
                self.camera = cv2.VideoCapture(self.stream_url)
            else:
                # Windows下优先DSHOW，失败则MSMF，最后CAP_ANY
                opened = False
                backends = []
                try:
                    backends.append(cv2.CAP_DSHOW)
                except Exception:
                    pass
                try:
                    backends.append(cv2.CAP_MSMF)
                except Exception:
                    pass
                backends.append(cv2.CAP_ANY)
                for be in backends:
                    try:
                        self.camera = cv2.VideoCapture(self.camera_index, be)
                    except Exception:
                        self.camera = cv2.VideoCapture(self.camera_index)
                    if self.camera and self.camera.isOpened():
                        opened = True
                        break
                if not opened:
                    self.camera = cv2.VideoCapture(self.camera_index)
        except Exception as e:
            print(f"打开摄像头失败: {e}")

    def _reopen_camera(self):
        """重连摄像头源"""
        self._open_camera()

    def update_source(self, camera_type: str, camera_index: int, stream_url: str):
        """更新摄像头源设置并重启"""
        need_restart = (camera_type != self.camera_type or
                        camera_index != self.camera_index or
                        stream_url != self.stream_url)
        self.camera_type = camera_type
        self.camera_index = camera_index
        self.stream_url = stream_url
        if need_restart:
            was_running = self.running
            self.stop()
            if was_running:
                self.start()
    
    def get_frame(self) -> Optional[np.ndarray]:
        """获取当前帧"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
    
    def get_frame_base64(self, format='JPEG', quality=85) -> Optional[str]:
        """获取当前帧的base64编码（用于web显示）"""
        frame = self.get_frame()
        
        if frame is None:
            return None
        
        try:
            # 编码为JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            _, buffer = cv2.imencode('.jpg', frame, encode_param)
            
            # 转换为base64
            jpg_as_text = base64.b64encode(buffer).decode('utf-8')
            return f"data:image/jpeg;base64,{jpg_as_text}"
        
        except Exception as e:
            print(f"编码帧失败: {e}")
            return None
    
    def add_callback(self, callback: Callable):
        """添加帧回调函数"""
        if callback not in self.callbacks:
            self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """移除帧回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def is_running(self) -> bool:
        """检查摄像头是否在运行"""
        return self.running and self.camera is not None and self.camera.isOpened()
    
    def save_frame(self, filepath: str) -> bool:
        """
        保存当前帧到文件
        filepath: 保存路径
        返回: 是否成功
        """
        frame = self.get_frame()
        
        if frame is None:
            return False
        
        try:
            cv2.imwrite(filepath, frame)
            return True
        except Exception as e:
            print(f"保存帧失败: {e}")
            return False

