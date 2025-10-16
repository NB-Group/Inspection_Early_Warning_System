"""
环境测试脚本
用于检查依赖是否正确安装
"""

import sys


def test_python_version():
    """测试Python版本"""
    print("检查Python版本...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✓ Python版本: {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"✗ Python版本过低: {version.major}.{version.minor}.{version.micro}")
        print("  需要Python 3.8或更高版本")
        return False


def test_import(module_name, package_name=None):
    """测试模块导入"""
    try:
        __import__(module_name)
        print(f"✓ {package_name or module_name}")
        return True
    except ImportError as e:
        print(f"✗ {package_name or module_name} - {e}")
        return False


def test_opencv():
    """测试OpenCV"""
    try:
        import cv2
        print(f"✓ OpenCV {cv2.__version__}")
        
        # 测试人脸检测器
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        if cascade.empty():
            print("  ⚠ 人脸检测器加载失败")
            return False
        else:
            print("  ✓ 人脸检测器正常")
        
        return True
    except Exception as e:
        print(f"✗ OpenCV - {e}")
        return False


def test_deepface():
    """测试DeepFace"""
    try:
        import deepface
        print("✓ DeepFace")
        print("  ℹ 首次使用时会自动下载模型（约300MB）")
        return True
    except Exception as e:
        print(f"✗ DeepFace - {e}")
        return False


def test_camera():
    """测试摄像头"""
    try:
        import cv2
        print("\n检查摄像头...")
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("✗ 无法打开摄像头0")
            print("  提示：可能被其他程序占用，或不存在")
            return False
        
        ret, frame = cap.read()
        cap.release()
        
        if ret and frame is not None:
            h, w = frame.shape[:2]
            print(f"✓ 摄像头正常 (分辨率: {w}x{h})")
            return True
        else:
            print("✗ 无法读取摄像头画面")
            return False
            
    except Exception as e:
        print(f"✗ 摄像头测试失败 - {e}")
        return False


def main():
    """主测试函数"""
    print("=" * 50)
    print("消污除腐 - 环境测试")
    print("=" * 50)
    print()
    
    results = []
    
    # 测试Python版本
    results.append(test_python_version())
    print()
    
    # 测试核心依赖
    print("检查核心依赖...")
    results.append(test_opencv())
    results.append(test_deepface())
    results.append(test_import('webview', 'PyWebView'))
    results.append(test_import('PIL', 'Pillow'))
    results.append(test_import('numpy', 'NumPy'))
    results.append(test_import('tensorflow', 'TensorFlow'))
    print()
    
    # Windows特定依赖
    if sys.platform == 'win32':
        print("检查Windows依赖...")
        results.append(test_import('win32event', 'pywin32'))
        print()
    
    # 测试摄像头
    results.append(test_camera())
    print()
    
    # 总结
    print("=" * 50)
    total = len(results)
    passed = sum(results)
    
    if all(results):
        print(f"✓ 所有测试通过 ({passed}/{total})")
        print("\n环境配置正确，可以运行程序！")
        print("运行命令: python main.py")
    else:
        print(f"✗ 部分测试失败 ({passed}/{total})")
        print("\n请安装缺失的依赖:")
        print("pip install -r requirements.txt")
    
    print("=" * 50)


if __name__ == "__main__":
    main()
    input("\n按回车键退出...")



