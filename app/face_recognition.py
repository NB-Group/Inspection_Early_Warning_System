"""
人脸识别模块
使用OpenCV检测人脸 + DeepFace进行识别
"""

import cv2
import numpy as np
from deepface import DeepFace
import cv2
from pathlib import Path
from typing import List, Tuple, Optional
import threading
import time


class FaceRecognizer:
    """人脸识别器"""
    
    def __init__(self, model_name="Facenet512", detector_backend="opencv"):
        self.model_name = model_name
        self.detector_backend = detector_backend
        self.target_faces = []  # 目标人脸的embedding
        self.target_faces_info = []  # 目标人脸信息（文件名等）
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.last_detection_time = 0
        self.detection_lock = threading.Lock()
    
    def load_target_faces(self, face_configs: List):
        """
        加载目标人脸
        face_configs: 可以是字符串路径列表（兼容旧格式）或字典列表 [{"name": "xxx", "path": "xxx.jpg"}]
        """
        self.target_faces = []
        self.target_faces_info = []
        
        for face_config in face_configs:
            try:
                # 兼容旧格式（字符串）和新格式（字典）
                if isinstance(face_config, str):
                    face_path = face_config
                    face_name = Path(face_config).stem
                elif isinstance(face_config, dict):
                    face_path = face_config.get("path", "")
                    face_name = face_config.get("name", Path(face_path).stem)
                else:
                    continue
                
                path = Path(face_path)
                if not path.exists():
                    print(f"人脸图片不存在: {face_path}")
                    continue
                
                # 读取图像以兼容中文路径（使用imdecode方式）
                img = self._read_image_unicode_safe(path)
                if img is None:
                    print(f"无法读取人脸图片: {face_path}")
                    continue

                # 使用DeepFace提取特征（传入numpy数组，绕过路径编码限制）
                embedding = DeepFace.represent(
                    img_path=img,
                    model_name=self.model_name,
                    detector_backend=self.detector_backend,
                    enforce_detection=False
                )
                
                if embedding and len(embedding) > 0:
                    self.target_faces.append(embedding[0]["embedding"])
                    self.target_faces_info.append({
                        "path": str(path),
                        "name": face_name
                    })
                    print(f"成功加载目标人脸: {face_name} ({path.name})")
                else:
                    print(f"无法提取人脸特征: {face_path}")
                    
            except Exception as e:
                print(f"加载人脸失败: {e}")
        
        print(f"共加载 {len(self.target_faces)} 个目标人脸")
    
    def detect_faces(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """检测人脸位置（快速）"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )
        return faces
    
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
                        current_embedding = DeepFace.represent(
                            img_path=face_img,
                            model_name=self.model_name,
                            detector_backend="skip",  # 已经检测过了
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
                                    _, buffer = cv2.imencode('.jpg', face_img)
                                    face_base64 = base64.b64encode(buffer).decode('utf-8')
                                    person_info["face_image"] = f"data:image/jpeg;base64,{face_base64}"
                                except Exception:
                                    person_info["face_image"] = None
                                
                                result["matched_persons"].append(person_info)
                    
                    except Exception as e:
                        print(f"识别人脸时出错: {e}")
                        continue
                
                result["matched_count"] = len(result["matched_persons"])
                return result
            
            except Exception as e:
                print(f"识别过程出错: {e}")
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

