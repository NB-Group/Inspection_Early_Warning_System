"""
配置管理模块
"""

import json
from pathlib import Path
from typing import Dict, Any


class Config:
    """配置管理器"""
    
    DEFAULT_CONFIG = {
        "camera_type": "local",            # local 或 ip
        "camera_index": 0,                  # 本地摄像头索引
        "ip_camera_url": "",               # 单路IP摄像头URL（兼容旧配置）
        "enable_dual": False,               # 是否启用双路IP摄像头
        "ip_camera_front_url": "",         # 前置摄像头URL
        "ip_camera_back_url": "",          # 后置摄像头URL
        "ip_audio_url": "",                # 音频流URL（如IP Webcam的audio.wav）
        "db_threshold": 75,                  # 分贝阈值
        "db_hold_secs": 2,                   # 超阈值提示保持秒数
        "recognition_threshold": 0.6,
        "alert_duration": 3,
        "detection_interval": 0.5,
        "face_model": "SFace",
        "detector_backend": "retinaface",
        "show_detections": False,
        "min_face_size": 30,              # 最小人脸尺寸（像素，短边）
        "min_face_conf": 0.6,             # 最小检测置信度（0-1）
        "yolo_face_model_path": "",      # YOLOv8-face 模型路径（可选）
        "yunet_model_path": "",          # YuNet 模型路径（可选）
        # Ultralytics HUB 云端推理
        "use_ultralytics_api": False,
        "ultralytics_api_key": "",
        "ultralytics_model": "yolov8n-face",
        "ultralytics_api_endpoint": "https://api.ultralytics.com/v1/predict",
        "ultralytics_api_timeout": 4.0,
        "monitoring_enabled": False,  # 是否启用监控（持久化）
        "enable_haar_fallback": False, # 仅在严重异常时才回退Haar
        "faces": []  # 存储人脸信息列表 [{"name": "张三", "path": "data/faces/xxx.jpg"}, ...]
    }
    
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.data = self.load()
    
    def load(self) -> Dict[str, Any]:
        """加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 合并默认配置，确保新字段存在
                    return {**self.DEFAULT_CONFIG, **data}
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Load config failed: {e}")
                return self.DEFAULT_CONFIG.copy()
        return self.DEFAULT_CONFIG.copy()
    
    def save(self):
        """保存配置"""
        try:
            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            import logging
            logging.getLogger(__name__).info(f"Config saved: {self.config_file}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Save config failed: {e}")
    
    def get(self, key: str, default=None):
        """获取配置项"""
        return self.data.get(key, default)
    
    def set(self, key: str, value):
        """设置配置项"""
        self.data[key] = value
        self.save()
    
    def update(self, updates: Dict[str, Any]):
        """批量更新配置"""
        self.data.update(updates)
        self.save()

