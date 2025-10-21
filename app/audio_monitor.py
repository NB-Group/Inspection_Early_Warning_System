"""
音频监测模块：从IP音频流读取音频，估算分贝并提供超阈值提示。
默认支持IP Webcam的 /audio.wav 流（PCM WAV）。
"""

import threading
import time
import math
from typing import Optional
import requests
import numpy as np


class AudioMonitor:
    def __init__(self, audio_url: str, db_threshold: float = 75.0, hold_secs: float = 2.0, chunk_ms: int = 200):
        self.audio_url = audio_url
        self.db_threshold = db_threshold
        self.hold_secs = hold_secs
        self.chunk_ms = chunk_ms
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.current_db: float = 0.0
        self.last_high_ts: float = 0.0
        self.lock = threading.Lock()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        import logging
        logging.getLogger(__name__).info(f"Audio monitor started: {self.audio_url}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        import logging
        logging.getLogger(__name__).info("Audio monitor stopped")

    def _loop(self):
        # 简单实现：拉取audio.wav流，跳过WAV头（44字节），之后读取PCM数据
        # 注意：不同实现可能重复头部或采用不同编码，这里仅作尽力支持
        session = requests.Session()
        try:
            with session.get(self.audio_url, stream=True, timeout=10) as resp:
                resp.raise_for_status()
                raw = resp.raw
                # 尝试跳过WAV头
                try:
                    raw.read(44)
                except Exception:
                    pass
                bytes_per_chunk = int(0.001 * self.chunk_ms * 16000 * 2)  # 假设16kHz, 16-bit mono
                while self.running:
                    try:
                        data = raw.read(bytes_per_chunk)
                        if not data:
                            time.sleep(0.1)
                            continue
                        # 计算RMS→dBFS近似
                        pcm = np.frombuffer(data, dtype=np.int16)
                        if pcm.size == 0:
                            continue
                        rms = np.sqrt(np.mean(pcm.astype(np.float32) ** 2))
                        db = 20.0 * math.log10(max(rms, 1.0) / 32768.0) + 100.0  # 粗略平移到正值区间
                        with self.lock:
                            self.current_db = float(max(0.0, db))
                            if self.current_db >= self.db_threshold:
                                self.last_high_ts = time.time()
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Audio read error: {e}")
                        time.sleep(0.3)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Audio connect failed: {e}")

    def get_status(self):
        with self.lock:
            now = time.time()
            is_high = (now - self.last_high_ts) <= self.hold_secs
            return {
                "db": round(self.current_db, 1),
                "is_high": is_high,
                "threshold": self.db_threshold
            }


