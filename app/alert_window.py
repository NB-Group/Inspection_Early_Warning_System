"""
全屏警报窗口（使用多进程运行WebView，避免主线程限制）
"""

import webview
import threading
import time
import multiprocessing
from multiprocessing import Process, Pipe


ALERT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>警报</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-user-select: none;
            user-select: none;
        }
        
        body {
            background: #d32f2f;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            overflow: hidden;
            font-family: 'Microsoft YaHei', 'Arial', sans-serif;
            cursor: default;
        }
        
        .alert-container {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 90%;
            max-width: 1600px;
            gap: 80px;
            animation: fadeIn 0.3s ease-out;
        }
        
        .left-section {
            flex: 1;
            color: white;
        }
        
        .title {
            font-size: 72px;
            font-weight: 900;
            margin-bottom: 30px;
            line-height: 1.2;
        }
        
        .count {
            font-size: 56px;
            font-weight: 700;
            margin-bottom: 20px;
        }
        
        .subtitle {
            font-size: 48px;
            font-weight: 600;
            opacity: 0.95;
        }
        
        .right-section {
            display: flex;
            gap: 40px;
            flex-wrap: wrap;
            justify-content: center;
            align-items: center;
        }
        
        .person-card {
            text-align: center;
            animation: slideIn 0.4s ease-out;
        }
        
        .person-photo {
            width: 280px;
            height: 280px;
            border-radius: 20px;
            object-fit: cover;
            border: 6px solid white;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            background: white;
            margin-bottom: 20px;
        }
        
        .person-name {
            color: white;
            font-size: 42px;
            font-weight: 800;
            text-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }
        
        .close-btn {
            position: fixed;
            top: 40px;
            right: 40px;
            background: white;
            color: #d32f2f;
            border: none;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            font-size: 32px;
            font-weight: bold;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .close-btn:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 30px rgba(0, 0, 0, 0.4);
        }
        
        .close-btn:active {
            transform: scale(0.95);
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
            }
            to {
                opacity: 1;
            }
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
    </style>
</head>
<body>
    <button class="close-btn" onclick="closeAlert()">✕</button>
    
    <div class="alert-container">
        <div class="left-section">
            <div class="title">发现目标人员</div>
            <div class="count">共 <span id="count">1</span> 个</div>
            <div class="subtitle">正在赶来</div>
        </div>
        
        <div class="right-section" id="persons-container">
            <!-- 人员卡片将动态插入这里 -->
        </div>
    </div>
    
    <script>
        function closeAlert() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.close_alert();
            }
        }
        
        window.addEventListener('pywebviewready', function() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.get_persons().then(function(persons) {
                    displayPersons(persons);
                });
            }
        });
        
        function displayPersons(persons) {
            const container = document.getElementById('persons-container');
            const countEl = document.getElementById('count');
            
            container.innerHTML = '';
            countEl.textContent = persons.length;
            
            persons.forEach(function(person) {
                const card = document.createElement('div');
                card.className = 'person-card';
                
                const img = document.createElement('img');
                img.className = 'person-photo';
                // 优先使用实时裁切的人脸图像
                if (person.face_image) {
                    img.src = person.face_image;
                } else {
                    img.src = 'file:///' + person.path.replace(/\\\\/g,'/');
                }
                img.onerror = function() {
                    this.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="280" height="280"><rect fill="white"/></svg>';
                };
                
                const name = document.createElement('div');
                name.className = 'person-name';
                name.textContent = person.name;
                
                card.appendChild(img);
                card.appendChild(name);
                container.appendChild(card);
            });
        }
    </script>
</body>
</html>
"""


def _alert_process_main(conn, persons_info: list, alert_duration: int):
    """警报窗口子进程入口"""
    import json
    import sys
    
    should_close = {'value': False}
    window_ref = {'window': None}
    
    class AlertAPIWithConn:
        def __init__(self, persons, pipe_conn, window_container):
            self.persons_info = persons
            self.conn = pipe_conn
            self.window_container = window_container
        
        def get_persons(self):
            return self.persons_info
        
        def close_alert(self):
            """用户点击关闭按钮"""
            print("用户点击关闭按钮")
            should_close['value'] = True
            try:
                # 销毁窗口
                if self.window_container['window']:
                    self.window_container['window'].destroy()
            except Exception as e:
                print(f"销毁窗口失败: {e}")
            try:
                # 通知父进程
                self.conn.send({'cmd': 'user_close'})
            except Exception:
                pass
            # 退出程序
            sys.exit(0)
    
    api = AlertAPIWithConn(persons_info, conn, window_ref)
    window = webview.create_window(
        '警报',
        html=ALERT_HTML_TEMPLATE,
        js_api=api,
        fullscreen=True,
        easy_drag=False,
        frameless=True,
        on_top=True,
        background_color='#d32f2f'
    )
    window_ref['window'] = window

    last_update_time = time.time()

    def listener():
        nonlocal last_update_time
        while not should_close['value']:
            # 自动关闭检查
            if time.time() - last_update_time >= alert_duration:
                print("自动关闭警报（超时）")
                should_close['value'] = True
                try:
                    window.destroy()
                except Exception as e:
                    print(f"自动关闭失败: {e}")
                sys.exit(0)

            if conn.poll(0.1):
                try:
                    msg = conn.recv()
                    if not isinstance(msg, dict):
                        continue
                    cmd = msg.get('cmd')
                    if cmd == 'update':
                        persons_info_new = msg.get('persons', [])
                        last_update_time = time.time()
                        try:
                            # 更新人员显示
                            persons_json = json.dumps(persons_info_new, ensure_ascii=False)
                            window.evaluate_js(f"displayPersons({persons_json});")
                        except Exception as e:
                            print(f"更新人员信息失败: {e}")
                    elif cmd == 'close' or cmd == 'user_close':
                        print("收到关闭命令")
                        should_close['value'] = True
                        try:
                            window.destroy()
                        except Exception as e:
                            print(f"关闭窗口失败: {e}")
                        sys.exit(0)
                except Exception as e:
                    print(f"处理消息失败: {e}")
            time.sleep(0.05)

    threading.Thread(target=listener, daemon=True).start()
    
    try:
        webview.start(debug=False)
    except Exception as e:
        print(f"WebView启动异常: {e}")
    finally:
        print("警报窗口进程退出")
        sys.exit(0)


class AlertWindow:
    """全屏警报窗口管理器（父进程控制）"""
    def __init__(self):
        self.alert_duration = 3
        self.proc: Process | None = None
        self.pipe = None
        self.last_update_time = 0
        self.is_showing = False
        self.last_persons_hash = None  # 用于防止频繁更新
        self.user_closed = False  # 用户是否手动关闭了警报
        self.monitoring_listener_active = False  # 监听器线程是否激活

    def show(self, persons_info: list):
        """
        显示警报窗口
        persons_info: [{"name": "xxx", "path": "xxx.jpg", "similarity": 0.85, "face_image": base64}, ...]
        """
        import json
        
        self.last_update_time = time.time()
        
        # 如果用户手动关闭了警报，在本次识别周期内不再弹出
        if self.user_closed:
            return
        
        # 如果窗口已经存在且还活着，更新内容
        if self.proc and self.proc.is_alive():
            try:
                self.pipe.send({'cmd': 'update', 'persons': persons_info})
            except Exception as e:
                print(f"更新警报窗口失败: {e}")
                # 如果更新失败，可能进程已死，清理并重建
                self.hide()
            else:
                return
        
        # 创建新窗口
        self.is_showing = True
        parent_conn, child_conn = Pipe()
        self.pipe = parent_conn
        self.proc = Process(
            target=_alert_process_main, 
            args=(child_conn, persons_info, self.alert_duration), 
            daemon=True,
        )
        self.proc.start()
        print("警报窗口已启动")
        
        # 启动监听线程，监听用户关闭事件
        if not self.monitoring_listener_active:
            self.monitoring_listener_active = True
            threading.Thread(target=self._listen_for_close, daemon=True).start()

    def _listen_for_close(self):
        """监听子进程发来的关闭消息"""
        while self.proc and self.proc.is_alive():
            if self.pipe and self.pipe.poll(0.1):
                try:
                    msg = self.pipe.recv()
                    if isinstance(msg, dict) and msg.get('cmd') == 'user_close':
                        print("收到用户关闭警报的消息")
                        self.user_closed = True
                        self.is_showing = False
                except Exception as e:
                    print(f"监听关闭消息失败: {e}")
            time.sleep(0.1)
        self.monitoring_listener_active = False

    def hide(self, user_initiated=False):
        """关闭警报窗口
        user_initiated: 是否为用户主动关闭
        """
        if self.proc and self.proc.is_alive():
            try:
                self.pipe.send({'cmd': 'close'})
            except Exception:
                pass
            # 给进程一点时间关闭
            time.sleep(0.1)
            if self.proc.is_alive():
                self.proc.terminate()
                self.proc.join(timeout=1.0)
        self.proc = None
        self.pipe = None
        self.is_showing = False
        self.last_persons_hash = None
        if user_initiated:
            self.user_closed = True

    def update(self, recognition_result: dict):
        """
        更新警报状态
        recognition_result: {
            "total_faces": 总人数,
            "matched_count": 匹配人数,
            "matched_persons": [...]
        }
        """
        current_time = time.time()
        matched_count = recognition_result.get("matched_count", 0)
        matched_persons = recognition_result.get("matched_persons", [])
        
        if matched_count > 0:
            self.last_update_time = current_time
            self.show(matched_persons)
        else:
            # 没有检测到目标人员
            if self.proc and self.proc.is_alive():
                # 检查是否超过自动关闭时间
                if current_time - self.last_update_time >= self.alert_duration:
                    self.hide()
            
            # 重要：当没有检测到目标时，重置用户关闭标志
            # 这样下次识别到目标时，警报会重新弹出（新的识别周期）
            if self.user_closed:
                print("目标已离开，重置警报状态，下次识别会重新弹窗")
                self.user_closed = False

    def set_alert_duration(self, duration: int):
        self.alert_duration = duration


# 分贝过高弹窗（多进程，避免主线程限制）
DB_ALERT_HTML = """
<!DOCTYPE html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>
<style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#8B0000;font-family:'Microsoft YaHei',sans-serif;color:#fff}
.box{text-align:center}
.title{font-size:80px;font-weight:900;margin-bottom:20px}
.db{font-size:56px;font-weight:800}
.hint{margin-top:20px;font-size:24px;opacity:.9}
.close{position:fixed;top:30px;right:30px;background:#fff;color:#8B0000;border:none;width:60px;height:60px;border-radius:50%;font-size:28px;font-weight:bold;cursor:pointer}
</style></head>
<body>
  <button class='close' onclick='window.pywebview.api.close_db()'>✕</button>
  <div class='box'>
    <div class='title'>噪声过高</div>
    <div class='db' id='db'>-- dB</div>
    <div class='hint'>请保持安静或降低音量</div>
  </div>
  <script>
    window.addEventListener('pywebviewready',()=>{
      setInterval(async()=>{
        const s = await window.pywebview.api.get_db();
        if(s && s.db!==undefined){document.getElementById('db').textContent = s.db + ' dB';}
      },300);
    })
  </script>
</body></html>
"""

class _DbAPI:
    def __init__(self, conn):
        self.conn = conn
        self._db = 0.0
    def get_db(self):
        try:
            # 请求最新值
            self.conn.send({'cmd':'pull'})
            if self.conn.poll(0.1):
                msg = self.conn.recv()
                if isinstance(msg, dict) and 'db' in msg:
                    self._db = msg['db']
        except Exception:
            pass
        return {'db': round(float(self._db),1)}
    def close_db(self):
        try:
            self.conn.send({'cmd':'close'})
        except Exception:
            pass

def _db_alert_process_main(conn):
    api = _DbAPI(conn)
    win = webview.create_window('噪声过高', html=DB_ALERT_HTML, js_api=api, fullscreen=True, frameless=True, on_top=True, background_color='#8B0000')
    def listener():
        while True:
            try:
                if conn.poll(0.1):
                    msg = conn.recv()
                    if not isinstance(msg, dict):
                        continue
                    if msg.get('cmd') == 'update':
                        # 更新当前分贝
                        try:
                            db = msg.get('db', 0.0)
                            win.evaluate_js(f"document.getElementById('db').textContent='{round(float(db),1)} dB';")
                        except Exception:
                            pass
                    elif msg.get('cmd') in ('close','user_close'):
                        try:
                            win.destroy()
                        except Exception:
                            pass
                        break
            except Exception:
                break
            time.sleep(0.05)
    threading.Thread(target=listener, daemon=True).start()
    webview.start(debug=False)

class DbAlertWindow:
    def __init__(self):
        from multiprocessing import Process, Pipe
        self.Process = Process
        self.Pipe = Pipe
        self.proc = None
        self.pipe = None
        self.last_db = 0.0

    def show(self, db_value: float):
        self.last_db = float(db_value)
        if self.proc and self.proc.is_alive():
            try:
                self.pipe.send({'cmd':'update','db': self.last_db})
            except Exception:
                pass
            return
        parent_conn, child_conn = self.Pipe()
        self.pipe = parent_conn
        self.proc = self.Process(target=_db_alert_process_main, args=(child_conn,), daemon=True)
        self.proc.start()
        # 初始值
        try:
            self.pipe.send({'cmd':'update','db': self.last_db})
        except Exception:
            pass

    def hide(self):
        if self.proc and self.proc.is_alive():
            try:
                self.pipe.send({'cmd':'close'})
            except Exception:
                pass
            self.proc.join(timeout=1.0)
        self.proc = None
        self.pipe = None

