"""
进程间通信模块
用于唤醒已运行的实例
"""

import socket
import threading
import time

IPC_PORT = 39527
WAKE_COMMAND = "WAKE_SETTINGS"


class IPCServer:
    """IPC服务器，监听唤醒命令"""
    
    def __init__(self, on_wake_callback):
        self.on_wake_callback = on_wake_callback
        self.running = False
        self.server_thread = None
        self.sock = None
    
    def start(self):
        """启动IPC服务器"""
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
    
    def _run_server(self):
        """服务器主循环"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('127.0.0.1', IPC_PORT))
            self.sock.listen(1)
            self.sock.settimeout(1.0)
            
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                    data = conn.recv(1024).decode('utf-8')
                    if data == WAKE_COMMAND:
                        self.on_wake_callback()
                    conn.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"IPC服务器错误: {e}")
        except Exception as e:
            print(f"无法启动IPC服务器: {e}")
        finally:
            if self.sock:
                self.sock.close()
    
    def stop(self):
        """停止IPC服务器"""
        self.running = False
        if self.server_thread:
            self.server_thread.join(timeout=2.0)


def wake_settings_window():
    """向已运行的实例发送唤醒命令"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(('127.0.0.1', IPC_PORT))
        sock.send(WAKE_COMMAND.encode('utf-8'))
        sock.close()
        print("已发送唤醒命令")
    except Exception as e:
        print(f"无法连接到运行中的实例: {e}")



