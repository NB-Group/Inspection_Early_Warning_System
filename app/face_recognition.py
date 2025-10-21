"""
人脸识别模块
使用OpenCV检测人脸 + DeepFace进行识别
"""

import cv2
import numpy as np
import logging
# 延迟导入DeepFace/RetinaFace，避免启动时阻塞
DeepFace = None
RetinaFace = None
def _lazy_import_deepface():
    global DeepFace
    if DeepFace is None:
        from deepface import DeepFace as _DF
        DeepFace = _DF
    return DeepFace
def _lazy_import_retinaface():
    global RetinaFace
    if RetinaFace is None:
        from retinaface import RetinaFace as _RF
        RetinaFace = _RF
    return RetinaFace
try:
    from ultralytics import YOLO
except Exception:
    YOLO = None
import cv2
from pathlib import Path
from typing import List, Tuple, Optional
import threading
import time
import base64
import json
import requests
import multiprocessing as mp


logger = logging.getLogger(__name__)

def build_face_embeddings_worker(conn, items, model_name):
    """Top-level worker for multiprocessing on Windows.
    Computes embeddings using OpenCV SFace (preferred) or DeepFace fallback.
    """
    try:
        import cv2 as _cv2
        from pathlib import Path as _P
        import numpy as _np
        use_sface = str(model_name).lower().startswith('sface') and hasattr(_cv2, 'FaceRecognizerSF_create')

        recognizer = None
        if use_sface:
            model_path = _P('data/models/face_recognition_sface_2021dec.onnx')
            if not model_path.exists():
                try:
                    model_path.parent.mkdir(parents=True, exist_ok=True)
                    import urllib.request
                    url = 'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'
                    urllib.request.urlretrieve(url, str(model_path))
                except Exception:
                    pass
            if model_path.exists():
                try:
                    recognizer = _cv2.FaceRecognizerSF_create(str(model_path), '')
                except Exception:
                    recognizer = None

        if not use_sface or recognizer is None:
            # Fallback to DeepFace inside subprocess
            from deepface import DeepFace as _DF

        results = []
        for it in items:
            if isinstance(it, str):
                face_path = it
                face_name = _P(it).stem
            elif isinstance(it, dict):
                face_path = it.get('path', '')
                face_name = it.get('name', _P(face_path).stem)
            else:
                continue
            p = _P(face_path)
            try:
                data = _np.fromfile(str(p), dtype=_np.uint8)
                img = _cv2.imdecode(data, _cv2.IMREAD_COLOR)
            except Exception:
                img = None
            if img is None:
                continue
            if use_sface and recognizer is not None:
                try:
                    feat = recognizer.feature(img)
                    if feat is None:
                        continue
                    results.append({'name': face_name, 'path': str(p), 'embedding': feat.flatten().tolist()})
                except Exception:
                    continue
            else:
                try:
                    emb = _DF.represent(img_path=img, model_name=model_name, detector_backend='skip', enforce_detection=False)
                    if emb and len(emb) > 0:
                        results.append({'name': face_name, 'path': str(p), 'embedding': emb[0]['embedding']})
                except Exception:
                    continue
        try:
            conn.send(results)
        except Exception:
            pass
    except Exception:
        try:
            conn.send([])
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

class FaceRecognizer:
    """人脸识别器"""
    
    def __init__(self, model_name="Facenet512", detector_backend="retinaface"):
        self.model_name = model_name
        self.detector_backend = detector_backend
        self.target_faces = []  # 目标人脸的embedding
        self.target_faces_info = []  # 目标人脸信息（文件名等）
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.last_detection_time = 0
        self.detection_lock = threading.Lock()
        # 检测过滤参数（可被配置覆盖）
        self.min_face_size = 30
        self.min_confidence = 0.6
        # YOLO/YN（YuNet）相关
        self._yolo_model = None
        self._yolo_model_path = None
        self._yunet = None
        self._yunet_model_path = None
        # OpenCV SFace (lightweight, TF-free)
        self._sface = None
        self._sface_model_path = None
        self.use_opencv_sface = str(model_name).lower().startswith('sface')

    def set_detection_filters(self, min_size: int = None, min_conf: float = None):
        """设置检测过滤参数"""
        if isinstance(min_size, int) and min_size > 0:
            self.min_face_size = min_size
        if isinstance(min_conf, (int, float)) and 0 <= min_conf <= 1:
            self.min_confidence = float(min_conf)

    def set_detector_backend(self, backend: str, yolo_model_path: str = "", yunet_model_path: str = ""):
        """切换检测器后端。backend: 'retinaface' | 'yolov8-face' | 'yunet'"""
        backend = (backend or 'retinaface').lower()
        self.detector_backend = backend
        # 清理现有模型
        self._yolo_model = None
        self._yunet = None
        self._yolo_model_path = None
        self._yunet_model_path = None

        if backend == 'yolov8-face' and YOLO is not None:
            try:
                self._yolo_model_path = yolo_model_path
                self._yolo_model = YOLO(yolo_model_path) if yolo_model_path else YOLO('yolov8n')
            except Exception:
                self._yolo_model = None
        elif backend == 'yunet':
            try:
                # YuNet 需要 ONNX 模型
                # 默认尝试 data/models/face_detection_yunet_2023mar.onnx
                from pathlib import Path
                default_path = Path('data/models/face_detection_yunet_2023mar.onnx')
                model_path = Path(yunet_model_path) if yunet_model_path else default_path
                if not model_path.exists():
                    # 尝试自动下载（网络不可用时忽略）
                    try:
                        model_path.parent.mkdir(parents=True, exist_ok=True)
                        import urllib.request
                        url = 'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'
                        urllib.request.urlretrieve(url, str(model_path))
                    except Exception:
                        pass
                if model_path.exists() and hasattr(cv2, 'FaceDetectorYN_create'):
                    self._yunet_model_path = str(model_path)
                    # 先用占位尺寸创建，实际检测前会 setInputSize
                    self._yunet = cv2.FaceDetectorYN_create(self._yunet_model_path, "", (320, 320), self.min_confidence, 0.3, 5000)
                else:
                    self._yunet = None
            except Exception:
                self._yunet = None
    
    def load_target_faces(self, face_configs: List):
        """
        加载目标人脸
        face_configs: 可以是字符串路径列表（兼容旧格式）或字典列表 [{"name": "xxx", "path": "xxx.jpg"}]
        """
        self.target_faces = []
        self.target_faces_info = []

        # 优先使用 OpenCV SFace（纯CPU、轻量，避免TF）
        if self.use_opencv_sface and hasattr(cv2, 'FaceRecognizerSF_create'):
            try:
                model_path = Path('data/models/face_recognition_sface_2021dec.onnx')
                if not model_path.exists():
                    try:
                        model_path.parent.mkdir(parents=True, exist_ok=True)
                        import urllib.request
                        url = 'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'
                        urllib.request.urlretrieve(url, str(model_path))
                    except Exception:
                        pass
                if not model_path.exists():
                    logger.warning('SFace model not found and download failed; falling back to DeepFace (may be heavy).')
                else:
                    self._sface = cv2.FaceRecognizerSF_create(str(model_path), '')
            except Exception as e:
                logger.warning(f'Create SFace failed: {e}. Falling back to DeepFace.')
                self._sface = None

            if self._sface is not None:
                for face_config in face_configs:
                    if isinstance(face_config, str):
                        face_path = face_config
                        face_name = Path(face_config).stem
                    elif isinstance(face_config, dict):
                        face_path = face_config.get('path', '')
                        face_name = face_config.get('name', Path(face_path).stem)
                    else:
                        continue
                    path = Path(face_path)
                    if not path.exists():
                        logger.warning(f'Face image not found: {face_path}')
                        continue
                    img = self._read_image_unicode_safe(path)
                    if img is None:
                        logger.warning(f'Cannot read face image: {face_path}')
                        continue
                    try:
                        feat = self._sface.feature(img)
                        if feat is None:
                            continue
                        self.target_faces.append(feat.flatten().tolist())
                        self.target_faces_info.append({'path': str(path), 'name': face_name})
                        logger.info(f"Loaded face: {face_name} ({path.name})")
                    except Exception as e:
                        logger.warning(f'Extract SFace feature failed: {e}')
                logger.info(f'Total loaded faces: {len(self.target_faces)}')
                return

        # DeepFace 子进程路径（避免TF阻塞主进程）
        parent_conn, child_conn = mp.Pipe()

        proc = mp.Process(target=build_face_embeddings_worker, args=(child_conn, face_configs, self.model_name), daemon=True)
        proc.start()
        try:
            results = parent_conn.recv()  # 阻塞等待子进程返回，但主UI不受影响
        except Exception:
            results = []
        finally:
            try:
                proc.join(timeout=0.1)
            except Exception:
                pass

        for r in results:
            self.target_faces.append(r['embedding'])
            self.target_faces_info.append({'path': r['path'], 'name': r['name']})
            logger.info(f"Loaded face: {r['name']} ({Path(r['path']).name})")
        logger.info(f"Total loaded faces: {len(self.target_faces)}")
    
    def detect_faces(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """检测人脸位置（支持 YOLOv8-face / RetinaFace / YuNet / Ultralytics-API；失败时回退 Haar）"""
        # YOLOv8-face / YuNet / RetinaFace
        try:
            faces = []
            # 云端通路（通过环境配置传入）
            if getattr(self, 'use_ultra_api', False):
                try:
                    h, w = frame.shape[:2]
                    # 压缩到较小尺寸以降低带宽
                    import cv2
                    max_side = 640
                    scale = min(max_side / max(h, w), 1.0)
                    resized = cv2.resize(frame, (int(w*scale), int(h*scale))) if scale < 1.0 else frame
                    _, buf = cv2.imencode('.jpg', resized, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    img_b64 = base64.b64encode(buf).decode('utf-8')
                    endpoint = (self.ultra_api_endpoint or 'https://api.ultralytics.com/v1/predict')
                    headers = {'x-api-key': self.ultra_api_key}
                    is_dedicated = 'dedicated' in endpoint.lower()
                    payload = {
                        'image': img_b64,
                    }
                    if not is_dedicated:
                        model_name = (self.ultra_model or 'yolov8n-face').strip()
                        if model_name:
                            payload['model'] = model_name
                    resp = requests.post(endpoint,
                                         headers=headers, json=payload, timeout=getattr(self, 'ultra_api_timeout', 4.0))
                    if resp.ok:
                        data = resp.json() or {}
                        preds = data.get('data') or []
                        for item in preds:
                            # item: {"box": {"x1":...,"y1":...,"x2":...,"y2":...}, "confidence": 0.9, "class":0}
                            box = (item.get('box') or {})
                            x1, y1, x2, y2 = box.get('x1'), box.get('y1'), box.get('x2'), box.get('y2')
                            conf = float(item.get('confidence', 1.0))
                            if None in (x1, y1, x2, y2):
                                continue
                            # 若做了resize，需按比例还原到原图坐标
                            if scale < 1.0:
                                inv = 1.0/scale
                                x1, y1, x2, y2 = x1*inv, y1*inv, x2*inv, y2*inv
                            wbox, hbox = int(x2 - x1), int(y2 - y1)
                            x, y = int(x1), int(y1)
                            if wbox <= 0 or hbox <= 0:
                                continue
                            if min(wbox, hbox) < self.min_face_size:
                                continue
                            if conf < self.min_confidence:
                                continue
                            faces.append((x, y, wbox, hbox))
                except Exception:
                    pass
            elif self.detector_backend == 'yolov8-face' and getattr(self, '_yolo_model', None) is not None:
                # 本地 YOLOv8-face
                # 统一推理接口，img直接传ndarray
                preds = self._yolo_model(frame, verbose=False)
                # 取第一张图片的预测
                if preds and len(preds) > 0:
                    boxes = preds[0].boxes
                    if boxes is not None:
                        for b in boxes:
                            conf = float(b.conf[0]) if b.conf is not None else 1.0
                            x1, y1, x2, y2 = map(float, b.xyxy[0].tolist())
                            w, h = int(x2 - x1), int(y2 - y1)
                            x, y = int(x1), int(y1)
                            if w <= 0 or h <= 0:
                                continue
                            if min(w, h) < self.min_face_size:
                                continue
                            if conf < self.min_confidence:
                                continue
                            faces.append((x, y, w, h))
            elif self.detector_backend == 'yunet' and getattr(self, '_yunet', None) is not None:
                h, w = frame.shape[:2]
                try:
                    self._yunet.setInputSize((w, h))
                    retval, detections = self._yunet.detect(frame)
                    # detections: Nx15 -> x, y, w, h, ..., score
                    if detections is not None and len(detections) > 0:
                        for det in detections:
                            x, y, bw, bh = det[0:4]
                            score = float(det[14]) if len(det) >= 15 else 1.0
                            x, y, bw, bh = int(x), int(y), int(bw), int(bh)
                            if bw <= 0 or bh <= 0:
                                continue
                            if min(bw, bh) < self.min_face_size:
                                continue
                            if score < self.min_confidence:
                                continue
                            faces.append((x, y, bw, bh))
                except Exception:
                    pass
            else:
                # RetinaFace 返回字典：{'face_1': {'score':0.99, 'facial_area':[x1,y1,x2,y2], ...}, ...}
                RF = _lazy_import_retinaface()
                det = RF.detect_faces(frame)
                if isinstance(det, dict):
                    for k, v in det.items():
                        area = v.get('facial_area') or []
                        if len(area) == 4:
                            x1, y1, x2, y2 = area
                            w, h = int(x2 - x1), int(y2 - y1)
                            x, y = int(x1), int(y1)
                            conf = float(v.get('score', 1.0))
                            if w <= 0 or h <= 0:
                                continue
                            if min(w, h) < self.min_face_size:
                                continue
                            if conf < self.min_confidence:
                                continue
                            faces.append((x, y, w, h))
            if faces:
                return faces
        except Exception as e:
            # 若主检测流程异常，按配置决定是否回退
            if not getattr(self, 'enable_haar_fallback', False):
                return []
            # 否则继续回退到Haar
            pass
        # 非异常路径：仅当开启回退时走Haar
        if getattr(self, 'enable_haar_fallback', False):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.15,
                minNeighbors=6,
                minSize=(self.min_face_size, self.min_face_size)
            )
            return faces
        return []
    
    def recognize_faces(self, frame: np.ndarray, threshold: float = 0.6):
        """
        识别画面中的人脸
        返回: {
            "total_faces": 总人数,
            "matched_count": 匹配人数,
            "matched_persons": [{"name": "xxx", "path": "xxx.jpg", "similarity": 0.85, "face_image": base64}, ...]
        }
        """
        import base64
        import cv2 as _cv2
        
        result = {
            "total_faces": 0,
            "matched_count": 0,
            "matched_persons": []
        }
        
        if not self.target_faces:
            return result
        
        with self.detection_lock:
            try:
                # 快速检测人脸
                faces = self.detect_faces(frame)
                result["total_faces"] = len(faces)
                
                if len(faces) == 0:
                    return result
                
                # 对每个检测到的人脸进行识别
                matched_persons_set = set()  # 用于去重
                
                for (x, y, w, h) in faces:
                    # 提取人脸区域
                    face_img = frame[y:y+h, x:x+w]
                    
                    if face_img.size == 0:
                        continue
                    
                    try:
                        # 提取当前人脸的embedding
                        if self.use_opencv_sface and hasattr(cv2, 'FaceRecognizerSF_create'):
                            if self._sface is None:
                                # 预加载SFace
                                try:
                                    model_path = Path('data/models/face_recognition_sface_2021dec.onnx')
                                    if not model_path.exists():
                                        try:
                                            model_path.parent.mkdir(parents=True, exist_ok=True)
                                            import urllib.request
                                            url = 'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'
                                            urllib.request.urlretrieve(url, str(model_path))
                                        except Exception:
                                            pass
                                    if model_path.exists():
                                        self._sface = cv2.FaceRecognizerSF_create(str(model_path), '')
                                except Exception:
                                    self._sface = None
                            if self._sface is None:
                                current_embedding = []
                            else:
                                # ensure correct cv2 alias is used
                                feat = self._sface.feature(face_img)
                                current_embedding = [{'embedding': feat.flatten().tolist()}] if feat is not None else []
                        else:
                            DF = _lazy_import_deepface()
                            current_embedding = DF.represent(
                                img_path=face_img,
                                model_name=self.model_name,
                                detector_backend="skip",
                                enforce_detection=False
                            )
                        
                        if not current_embedding or len(current_embedding) == 0:
                            continue
                        
                        current_vec = np.array(current_embedding[0]["embedding"])
                        
                        # 与每个目标人脸比对，找出最佳匹配
                        best_match_idx = -1
                        best_similarity = 0
                        
                        for idx, target_vec in enumerate(self.target_faces):
                            target_vec = np.array(target_vec)
                            
                            # 计算余弦相似度
                            similarity = self._cosine_similarity(current_vec, target_vec)
                            
                            # 如果相似度超过阈值且是最佳匹配
                            if similarity > threshold and similarity > best_similarity:
                                best_similarity = similarity
                                best_match_idx = idx
                        
                        # 如果找到匹配
                        if best_match_idx >= 0:
                            person_info = self.target_faces_info[best_match_idx].copy()
                            person_info["similarity"] = float(best_similarity)
                            person_name = person_info["name"]
                            
                            # 去重：同一个人只记录一次
                            if person_name not in matched_persons_set:
                                matched_persons_set.add(person_name)
                                
                                # 保存实时裁切的人脸图像（Base64编码）
                                try:
                                    # 裁切人脸区域并编码
                                    _, buffer = _cv2.imencode('.jpg', face_img)
                                    face_base64 = base64.b64encode(buffer).decode('utf-8')
                                    ts = int(time.time() * 1000)
                                    person_info["face_image"] = f"data:image/jpeg;base64,{face_base64}#t={ts}"
                                    person_info["ts"] = ts
                                except Exception:
                                    person_info["face_image"] = None
                                
                                person_info["box"] = [int(x), int(y), int(w), int(h)]
                                result["matched_persons"].append(person_info)
                    
                    except Exception as e:
                        logger.error(f"Error while recognizing a face: {e}")
                        continue
                
                result["matched_count"] = len(result["matched_persons"])
                return result
            
            except Exception as e:
                logger.error(f"Recognition pipeline error: {e}")
                return result
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算余弦相似度"""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def draw_faces(self, frame: np.ndarray, color=(0, 255, 0), thickness=2) -> np.ndarray:
        """在画面上标记检测到的人脸"""
        faces = self.detect_faces(frame)
        result_frame = frame.copy()
        
        for (x, y, w, h) in faces:
            cv2.rectangle(result_frame, (x, y), (x+w, y+h), color, thickness)
        
        return result_frame

    def _read_image_unicode_safe(self, path: Path) -> Optional[np.ndarray]:
        """以兼容中文路径的方式读取图像，返回BGR图像。"""
        try:
            # 使用np.fromfile + cv2.imdecode以支持非ASCII路径
            import numpy as np
            data = np.fromfile(str(path), dtype=np.uint8)
            if data.size == 0:
                return None
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None

