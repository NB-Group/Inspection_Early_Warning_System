"""
人脸识别预警系统
主程序入口
"""

import sys
import os
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')  # 抑制TF冗余日志
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
import win32event
import win32api
import winerror
from pathlib import Path

# 确保数据目录存在
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
FACES_DIR = DATA_DIR / "faces"
FACES_DIR.mkdir(exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"

# 单实例互斥锁
MUTEX_NAME = "Global\\NullifyBlightFaceRecognition"


def main():
    """主程序入口"""
    # 尝试创建互斥锁，确保单实例运行
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    last_error = win32api.GetLastError()
    
    if last_error == winerror.ERROR_ALREADY_EXISTS:
        # 程序已经在运行，唤醒设置窗口
        import logging
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).info("程序已在运行，正在唤醒设置窗口...")
        from app.ipc import wake_settings_window
        wake_settings_window()
        return
    
    try:
        # 启动主应用
        from app.application import Application
        app = Application()
        app.run()
    finally:
        # 释放互斥锁
        win32api.CloseHandle(mutex)


if __name__ == "__main__":
    main()



