"""
主应用程序
"""

import webview
import threading
import time
from pathlib import Path
import shutil
import ctypes

from app.config import Config
from app.camera import CameraMonitor
from app.face_recognition import FaceRecognizer
from app.alert_window import AlertWindow, DbAlertWindow
from app.ipc import IPCServer
from app.audio_monitor import AudioMonitor


# 数据目录
DATA_DIR = Path("data")
FACES_DIR = DATA_DIR / "faces"
CONFIG_FILE = DATA_DIR / "config.json"


class SettingsAPI:
    """设置界面API（避免暴露复杂对象给WebView，防止属性遍历报错）"""
    __slots__ = ('_app',)
    
    def __init__(self, app):
        # 存内部引用，外部不暴露
        self._app = app
    
    def get_config(self):
        """获取配置"""
        return self._app.config.data
    
    def get_face_image_base64(self, face_path):
        """获取人脸图片的Base64编码"""
        import base64
        try:
            with open(face_path, 'rb') as f:
                img_data = f.read()
            b64_data = base64.b64encode(img_data).decode('utf-8')
            # 判断文件扩展名
            ext = Path(face_path).suffix.lower()
            mime_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp'
            }
            mime_type = mime_map.get(ext, 'image/jpeg')
            return f"data:{mime_type};base64,{b64_data}"
        except Exception as e:
            print(f"加载图片失败 {face_path}: {e}")
            return None
    
    def save_config(self, updates):
        """保存配置"""
        app = self._app
        app.config.update(updates)
        
        # 如果摄像头索引改变，重启摄像头
        if 'camera_index' in updates:
            app.restart_camera()
        
        # 如果相机类型或URL/双路相关改变，重启摄像头
        cam_keys = {'camera_type','ip_camera_url','enable_dual','ip_camera_front_url','ip_camera_back_url'}
        if any(k in updates for k in cam_keys):
            app.restart_camera()
        
        # 音频相关参数变化，重启音频监测
        audio_keys = {'ip_audio_url','db_threshold','db_hold_secs'}
        if any(k in updates for k in audio_keys):
            app.restart_audio_monitor()

        # 如果识别参数改变，重新加载人脸
        if 'recognition_threshold' in updates or 'face_model' in updates:
            app.reload_faces()
        
        # 如果警报持续时间改变，更新警报窗口
        if 'alert_duration' in updates:
            app.alert_window.set_alert_duration(updates['alert_duration'])
        
        return True
    
    def add_face(self, file_path):
        """添加人脸图片（通过绝对路径）"""
        try:
            app = self._app
            if not file_path:
                raise ValueError("未接收到文件路径")
            source = Path(file_path)
            if not source.exists():
                raise FileNotFoundError(f"文件不存在: {file_path}")
            
            # 复制到faces目录
            destination = FACES_DIR / source.name
            
            # 如果文件名重复，添加数字后缀
            counter = 1
            while destination.exists():
                destination = FACES_DIR / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            
            shutil.copy2(source, destination)
            
            # 更新配置
            faces = app.config.get('faces', [])
            faces.append(str(destination))
            app.config.set('faces', faces)
            
            # 重新加载人脸
            app.reload_faces()
            
            return str(destination)
        
        except Exception as e:
            print(f"添加人脸失败: {e}")
            raise

    def add_face_base64(self, filename, data_url, name=None, angle_hint=None):
        """添加人脸图片（通过Base64 DataURL）
        filename: 前端提供的原始文件名
        data_url: 形如 data:image/jpeg;base64,xxxx 的字符串
        name: 人员名称（可选）
        angle_hint: 角度提示，如"正面"、"左侧"、"右侧"（可选）
        """
        import base64
        import re
        try:
            app = self._app
            if not data_url:
                raise ValueError("未接收到图片数据")

            # 解析DataURL
            match = re.match(r"data:(image\/[^;]+);base64,(.*)", data_url)
            if not match:
                raise ValueError("数据格式不正确")

            mime_type, b64_data = match.groups()
            ext_map = {
                'image/jpeg': '.jpg',
                'image/jpg': '.jpg',
                'image/png': '.png',
                'image/bmp': '.bmp',
                'image/gif': '.gif'
            }
            ext = ext_map.get(mime_type, Path(filename).suffix or '.jpg')

            # 目标文件名与路径
            base_name = Path(filename).stem or 'face'
            if not name:
                name = base_name
            
            # 如果有角度提示，加到文件名中
            if angle_hint:
                file_base = f"{base_name}_{angle_hint}"
            else:
                file_base = base_name
            
            destination = FACES_DIR / f"{file_base}{ext}"
            counter = 1
            while destination.exists():
                destination = FACES_DIR / f"{file_base}_{counter}{ext}"
                counter += 1

            # 写入文件
            FACES_DIR.mkdir(parents=True, exist_ok=True)
            with open(destination, 'wb') as f:
                f.write(base64.b64decode(b64_data))

            # 更新配置（新格式：字典）
            faces = app.config.get('faces', [])
            face_entry = {
                "name": name,
                "path": str(destination),
                "angle": angle_hint or "未指定"
            }
            faces.append(face_entry)
            app.config.set('faces', faces)

            # 重新加载人脸
            app.reload_faces()

            return str(destination)
        except Exception as e:
            print(f"添加人脸失败(Base64): {e}")
            raise
    
    def remove_face(self, face_path):
        """移除人脸"""
        try:
            app = self._app
            # 从配置中移除（兼容新旧格式）
            faces = app.config.get('faces', [])
            updated_faces = []
            removed = False
            
            for face in faces:
                # 旧格式：字符串
                if isinstance(face, str):
                    if face != face_path:
                        updated_faces.append(face)
                    else:
                        removed = True
                # 新格式：字典
                elif isinstance(face, dict):
                    if face.get('path') != face_path:
                        updated_faces.append(face)
                    else:
                        removed = True
            
            if removed:
                app.config.set('faces', updated_faces)
            
            # 删除文件
            file_path = Path(face_path)
            if file_path.exists():
                file_path.unlink()
            
            # 重新加载人脸
            app.reload_faces()
            
            return True
        
        except Exception as e:
            print(f"移除人脸失败: {e}")
            raise
    
    def start_monitoring(self):
        """开始监控"""
        app = self._app
        app.start_monitoring()
        # 持久化监控状态
        app.config.set('monitoring_enabled', True)
        return True
    
    def stop_monitoring(self):
        """停止监控"""
        app = self._app
        app.stop_monitoring()
        # 持久化监控状态
        app.config.set('monitoring_enabled', False)
        return True
    
    def get_preview_frame(self):
        """获取预览帧（Base64）"""
        app = self._app
        if app.camera and app.camera.is_running():
            return app.camera.get_frame_base64()
        return None
    
    def get_preview_frames(self):
        """获取双路预览帧"""
        app = self._app
        frames = {'front': None, 'back': None}
        if app.camera and app.camera.is_running():
            frames['front'] = app.camera.get_frame_base64()
        if app.camera_back and app.camera_back.is_running():
            frames['back'] = app.camera_back.get_frame_base64()
        return frames
    
    def get_audio_status(self):
        app = self._app
        if app.audio_monitor:
            return app.audio_monitor.get_status()
        return {"db": 0.0, "is_high": False, "threshold": app.config.get('db_threshold', 75)}

    def show_db_alert(self):
        try:
            app = self._app
            app.db_alert.show(app.audio_monitor.get_status if app.audio_monitor else (lambda: {"db": 0.0}))
            return True
        except Exception as e:
            print(f"显示分贝弹窗失败: {e}")
            return False

    def hide_db_alert(self):
        try:
            self._app.db_alert.hide()
            return True
        except Exception:
            return False
    
    # 窗口控制
    def minimize_window(self):
        try:
            app = self._app
            if app.settings_window:
                app.settings_window.minimize()
                return True
        except Exception as e:
            print(f"最小化失败: {e}")
        return False
    
    def toggle_maximize(self):
        app = self._app
        window = app.settings_window
        if not window:
            return False

        if not hasattr(app, 'window_original_geometry'):
            app.window_original_geometry = None

        if app.window_original_geometry is None:
            # Store original geometry and maximize
            app.window_original_geometry = {
                'x': window.x, 'y': window.y,
                'width': window.width, 'height': window.height
            }
            # Windows 工作区（不覆盖任务栏）
            try:
                SPI_GETWORKAREA = 0x0030
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                rect = RECT()
                ok = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                if ok:
                    work_x, work_y = rect.left, rect.top
                    work_w, work_h = rect.right - rect.left, rect.bottom - rect.top
                    window.move(work_x, work_y)
                    window.resize(work_w, work_h)
                else:
                    # 回退到屏幕尺寸
                    primary_screen = webview.screens[0]
                    window.move(primary_screen.x, primary_screen.y)
                    window.resize(primary_screen.width, primary_screen.height)
            except Exception:
                primary_screen = webview.screens[0]
                window.move(primary_screen.x, primary_screen.y)
                window.resize(primary_screen.width, primary_screen.height)
        else:
            # Restore
            geom = app.window_original_geometry
            window.resize(geom['width'], geom['height'])
            window.move(geom['x'], geom['y'])
            app.window_original_geometry = None
        return True
    
    def close_window(self):
        try:
            app = self._app
            if app.settings_window:
                app.settings_window.destroy()
                return True
        except Exception as e:
            print(f"关闭窗口失败: {e}")
        return False
    
    def save_snapshot(self):
        """保存摄像头快照"""
        try:
            from datetime import datetime
            from pathlib import Path
            
            # 创建screenshots目录
            screenshots_dir = Path("data/screenshots")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名（带时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_{timestamp}.jpg"
            filepath = screenshots_dir / filename
            
            # 保存帧
            if self._app.camera and self._app.camera.save_frame(str(filepath)):
                return {"success": True, "path": str(filepath), "filename": filename}
            else:
                return {"success": False, "error": "无法获取摄像头画面"}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def start_recording(self):
        """开始录制"""
        try:
            app = self._app
            from datetime import datetime
            from pathlib import Path
            records_dir = Path("data/records")
            records_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = records_dir / f"record_{ts}.mp4"
            if not app.camera or not app.camera.is_running():
                return {"success": False, "error": "摄像头未启动"}
            out_path = app.camera.start_recording(str(file_path))
            return {"success": True, "path": out_path}
        except Exception as e:
            print(f"开始录制失败: {e}")
            return {"success": False, "error": str(e)}
    
    def stop_recording(self):
        """停止录制"""
        try:
            app = self._app
            if not app.camera:
                return {"success": False, "error": "摄像头未初始化"}
            out_path = app.camera.stop_recording()
            return {"success": True, "path": out_path}
        except Exception as e:
            print(f"停止录制失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_monitoring_status(self):
        """获取监控状态"""
        return self._app.monitoring


class Application:
    """主应用程序"""
    
    def __init__(self):
        self.config = Config(CONFIG_FILE)
        self.camera = None
        self.camera_back = None
        self.face_recognizer = None
        self.alert_window = AlertWindow()
        self.db_alert = DbAlertWindow()
        self.ipc_server = None
        self.settings_window = None
        self.monitoring = False
        self.monitor_thread = None
        self.last_detection_time = 0
        self.audio_monitor = None
        
        # 初始化组件
        self._init_components()
    
    def _init_components(self):
        """初始化组件"""
        # 创建摄像头监控器（支持local/ip/双路）
        camera_type = self.config.get('camera_type', 'local')
        camera_index = self.config.get('camera_index', 0)
        ip_url = self.config.get('ip_camera_url', '')
        enable_dual = self.config.get('enable_dual', False)
        front_url = self.config.get('ip_camera_front_url', '') or ip_url
        back_url = self.config.get('ip_camera_back_url', '')
        self.camera = CameraMonitor(camera_index=camera_index, camera_type=camera_type, stream_url=front_url)
        if enable_dual and camera_type == 'ip' and back_url:
            self.camera_back = CameraMonitor(camera_index=0, camera_type='ip', stream_url=back_url)
        
        # 创建人脸识别器
        model_name = self.config.get('face_model', 'Facenet512')
        detector_backend = self.config.get('detector_backend', 'opencv')
        self.face_recognizer = FaceRecognizer(model_name, detector_backend)
        
        # 加载目标人脸
        faces = self.config.get('faces', [])
        if faces:
            print(f"正在加载 {len(faces)} 个目标人脸...")
            self.face_recognizer.load_target_faces(faces)
        
        # 设置警报持续时间
        alert_duration = self.config.get('alert_duration', 3)
        self.alert_window.set_alert_duration(alert_duration)
        
        # 启动摄像头（用于预览）
        try:
            self.camera.start()
        except Exception as e:
            print(f"启动摄像头失败: {e}")
        if self.camera_back:
            try:
                self.camera_back.start()
            except Exception as e:
                print(f"启动第二路摄像头失败: {e}")

        # 启动音频监测
        audio_url = self.config.get('ip_audio_url', '')
        if audio_url:
            try:
                db_th = float(self.config.get('db_threshold', 75))
                hold = float(self.config.get('db_hold_secs', 2))
                self.audio_monitor = AudioMonitor(audio_url, db_threshold=db_th, hold_secs=hold)
                self.audio_monitor.start()
            except Exception as e:
                print(f"音频监测启动失败: {e}")
    
    def restart_camera(self):
        """重启摄像头"""
        if self.camera:
            self.camera.stop()
        if self.camera_back:
            self.camera_back.stop()
            self.camera_back = None
        
        camera_type = self.config.get('camera_type', 'local')
        camera_index = self.config.get('camera_index', 0)
        ip_url = self.config.get('ip_camera_url', '')
        enable_dual = self.config.get('enable_dual', False)
        front_url = self.config.get('ip_camera_front_url', '') or ip_url
        back_url = self.config.get('ip_camera_back_url', '')
        self.camera = CameraMonitor(camera_index=camera_index, camera_type=camera_type, stream_url=front_url)
        if enable_dual and camera_type == 'ip' and back_url:
            self.camera_back = CameraMonitor(camera_index=0, camera_type='ip', stream_url=back_url)
        
        try:
            self.camera.start()
        except Exception as e:
            print(f"重启摄像头失败: {e}")
        if self.camera_back:
            try:
                self.camera_back.start()
            except Exception as e:
                print(f"重启第二路摄像头失败: {e}")

    def restart_audio_monitor(self):
        """重启音频监测"""
        if self.audio_monitor:
            try:
                self.audio_monitor.stop()
            except Exception:
                pass
            self.audio_monitor = None
        audio_url = self.config.get('ip_audio_url', '')
        if not audio_url:
            return
        try:
            db_th = float(self.config.get('db_threshold', 75))
            hold = float(self.config.get('db_hold_secs', 2))
            self.audio_monitor = AudioMonitor(audio_url, db_threshold=db_th, hold_secs=hold)
            self.audio_monitor.start()
        except Exception as e:
            print(f"音频监测启动失败: {e}")
    
    def reload_faces(self):
        """重新加载人脸"""
        faces = self.config.get('faces', [])
        print(f"重新加载 {len(faces)} 个目标人脸...")
        self.face_recognizer.load_target_faces(faces)
    
    def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            print("监控已在运行")
            return
        
        if not self.config.get('faces'):
            print("警告: 未添加任何目标人脸")
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        if self.monitoring:
            self.monitoring = False
            if self.monitor_thread:
                self.monitor_thread.join(timeout=2.0)
            
            # 隐藏警报窗口
            self.alert_window.hide()
            print("监控已停止")
        # 如果本来就没在监控，不打印任何消息
    
    def _monitor_loop(self):
        """监控主循环"""
        detection_interval = self.config.get('detection_interval', 0.5)
        threshold = self.config.get('recognition_threshold', 0.6)
        
        while self.monitoring:
            try:
                current_time = time.time()
                
                # 控制检测频率
                if current_time - self.last_detection_time < detection_interval:
                    time.sleep(0.05)
                    continue
                
                self.last_detection_time = current_time
                
                # 获取当前帧
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue
                
                # 识别人脸
                result = self.face_recognizer.recognize_faces(frame, threshold)
                
                # 更新警报状态
                matched_count = result.get("matched_count", 0)
                if matched_count > 0:
                    persons = result.get("matched_persons", [])
                    names = [p.get("name") for p in persons]
                    print(f"检测到目标人员: {', '.join(names)} (共 {matched_count} 个)")
                    self.alert_window.update(result)
                else:
                    self.alert_window.update(result)

                # 分贝过高提示
                if self.audio_monitor:
                    s = self.audio_monitor.get_status()
                    if s.get('is_high'):
                        # 显示分贝弹窗（传入当前dB数值）
                        self.db_alert.show(s.get('db', 0.0))
                    else:
                        self.db_alert.hide()
                
            except Exception as e:
                print(f"监控循环错误: {e}")
                time.sleep(0.5)
    
    def _wake_settings(self):
        """唤醒设置窗口"""
        # 尝试显示现有窗口
        if self.settings_window:
            try:
                print("正在唤醒设置窗口...")
                self.settings_window.show()
                print("设置窗口已唤醒")
                return
            except Exception as e:
                print(f"唤醒失败: {e}")
                print("窗口可能已经被完全销毁，请重启程序")
    
    def run(self):
        """运行应用程序"""
        # 启动IPC服务器
        self.ipc_server = IPCServer(self._wake_settings)
        self.ipc_server.start()
        
        # 读取HTML模板
        html_path = Path(__file__).parent / 'settings_ui.html'
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # 创建设置窗口
        api = SettingsAPI(self)
        self.settings_window = webview.create_window(
            '人脸识别预警系统 - 设置',
            html=html_content,
            js_api=api,
            width=1200,
            height=800,
            resizable=True,
            background_color='#0a0a0a',
            easy_drag=False,
            hidden=False,
            shadow=True,
            frameless=True
        )
        
        # 窗口关闭事件：统一隐藏，防止被销毁后无法唤醒
        def on_closing():
            print("隐藏设置窗口（阻止销毁），可通过唤醒或托盘/再次启动唤起")
            try:
                self.settings_window.hide()
            except Exception:
                pass
            # 返回 False 阻止实际关闭与销毁
            return False
        
        # 某些平台只触发 closed 事件，这里兜底：如果误关，尝试立即重新显示
        self.settings_window.events.closing += on_closing
        # 保留 closed 事件为无操作（真正退出请用标题栏的关闭按钮）
        
        # 恢复监控状态（延迟执行）
        def restore_monitoring_state():
            import time
            time.sleep(1)  # 等待窗口完全加载
            monitoring_enabled = self.config.get('monitoring_enabled', False)
            if monitoring_enabled and self.config.get('faces'):
                print("恢复监控状态...")
                self.start_monitoring()
        
        # 在后台线程中恢复监控状态
        threading.Thread(target=restore_monitoring_state, daemon=True).start()
        
        # 启动WebView
        webview.start(debug=False)
        
        # WebView关闭/隐藏后，检查是否需要继续运行
        print("WebView窗口已关闭/隐藏")
        
        if self.monitoring:
            print("监控正在运行，程序继续运行...")
            print("提示：再次运行程序可唤醒设置窗口")
            try:
                while True:
                    time.sleep(1)
                    if not self.monitoring:
                        print("监控已停止")
                        break
            except KeyboardInterrupt:
                print("收到中断信号，准备退出...")
        else:
            print("监控未启动，程序退出...")
        
        # 清理资源
        self.cleanup(force=True)
    
    def cleanup(self, force=False):
        """清理资源
        
        Args:
            force: 强制清理所有资源（用于程序退出）
        """
        # 检查是否有需要清理的资源
        has_resources = self.monitoring or self.camera or self.camera_back or self.ipc_server or self.audio_monitor
        
        if has_resources:
            print("正在清理资源...")
        
        # 强制清理或监控未运行时才停止
        if force or not self.monitoring:
            self.stop_monitoring()
            
            if self.camera:
                self.camera.stop()
            if self.camera_back:
                self.camera_back.stop()
                self.camera_back = None
                
            if self.ipc_server:
                self.ipc_server.stop()
            if self.audio_monitor:
                try:
                    self.audio_monitor.stop()
                except Exception:
                    pass
                self.audio_monitor = None
        
        if has_resources:
            print("清理完成")

