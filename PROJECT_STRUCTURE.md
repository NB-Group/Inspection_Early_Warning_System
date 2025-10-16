# 项目结构说明

## 目录结构

```
Inspection_Early_Warning_System/
│
├── main.py                      # 主程序入口
├── requirements.txt             # Python依赖列表
├── 启动.bat                     # Windows启动脚本
├── README.md                    # 项目说明
├── USAGE.md                     # 使用指南
├── PROJECT_STRUCTURE.md         # 本文件
├── .gitignore                   # Git忽略文件
│
├── app/                         # 应用程序模块
│   ├── __init__.py             # 模块初始化
│   ├── application.py          # 主应用程序类
│   ├── config.py               # 配置管理
│   ├── camera.py               # 摄像头监控
│   ├── face_recognition.py     # 人脸识别
│   ├── alert_window.py         # 警报窗口
│   ├── ipc.py                  # 进程间通信
│   └── settings_ui.html        # 设置界面HTML
│
└── data/                        # 数据目录（自动创建）
    ├── config.json             # 配置文件
    └── faces/                  # 目标人脸图片
        ├── person1.jpg
        ├── person2.jpg
        └── ...
```

## 模块说明

### main.py
- 程序入口点
- 实现单实例运行机制
- 处理互斥锁和实例唤醒

### app/application.py
- 主应用程序类
- 整合各个模块
- 管理应用程序生命周期
- 提供设置界面API

### app/config.py
- 配置管理器
- 负责配置的加载、保存
- 提供配置项访问接口

### app/camera.py
- 摄像头监控模块
- 摄像头初始化和管理
- 帧捕获和编码
- 回调机制

### app/face_recognition.py
- 人脸识别模块
- 基于OpenCV快速人脸检测
- 基于DeepFace高精度人脸识别
- 人脸特征提取和比对

### app/alert_window.py
- 全屏警报窗口
- 自动显示/隐藏
- 动画效果
- 自动关闭计时

### app/ipc.py
- 进程间通信
- 实现单实例唤醒
- Socket通信

### app/settings_ui.html
- 设置界面
- 现代化暗色主题
- 左右分栏布局
- 实时摄像头预览

## 数据流程

```
启动程序
  ↓
main.py (检查单实例)
  ↓
Application.__init__
  ↓
加载配置 → 初始化摄像头 → 加载人脸模型
  ↓
显示设置界面
  ↓
用户操作
  ├─ 添加人脸 → 保存到data/faces/ → 重新加载模型
  ├─ 调整设置 → 保存配置 → 更新相关组件
  └─ 开始监控 → 启动监控线程
                  ↓
            摄像头捕获 → 人脸检测 → 人脸识别
                  ↓
          检测到目标？
            ├─ 是 → 显示全屏警报
            └─ 否 → 继续监控
```

## 关键技术

### 人脸识别流程

1. **人脸检测** (OpenCV Haar Cascade)
   - 快速定位人脸区域
   - 实时性能好

2. **特征提取** (DeepFace + Facenet512)
   - 提取512维特征向量
   - 高精度识别

3. **相似度计算** (余弦相似度)
   - 计算特征向量相似度
   - 阈值判断是否匹配

### 单实例机制

1. 创建全局互斥锁
2. 检测是否已运行
3. 已运行则通过Socket唤醒
4. 未运行则创建新实例

### 界面技术栈

- **PyWebView**: Python与Web界面通信
- **HTML/CSS/JS**: 现代化界面设计
- **WebView API**: Python与JavaScript双向调用

## 性能优化

### 检测优化
- 先用OpenCV快速检测人脸位置
- 仅对检测到的区域进行深度识别
- 可调节检测间隔控制CPU占用

### 内存优化
- 预加载人脸特征向量
- 避免重复加载模型
- 及时释放临时图像数据

### 线程模型
- 主线程：UI界面
- 摄像头线程：持续捕获帧
- 监控线程：人脸识别处理
- IPC线程：监听唤醒请求

## 配置说明

### config.json 结构

```json
{
  "camera_index": 0,              // 摄像头索引
  "recognition_threshold": 0.6,   // 识别阈值
  "alert_duration": 3,            // 警报持续时间(秒)
  "detection_interval": 0.5,      // 检测间隔(秒)
  "face_model": "Facenet512",     // 人脸模型
  "detector_backend": "opencv",   // 检测后端
  "faces": [                      // 目标人脸列表
    "data/faces/person1.jpg",
    "data/faces/person2.jpg"
  ]
}
```

## 扩展建议

### 支持网络摄像头
修改 `app/camera.py`，支持RTSP/HTTP流：
```python
self.camera = cv2.VideoCapture('rtsp://...')
```

### 添加日志记录
记录识别历史、警报触发时间等

### 多目标分类
为不同人员设置不同的警报级别

### 远程通知
集成邮件、短信、企业微信等通知方式

### 数据统计
统计检测次数、识别准确率等数据



