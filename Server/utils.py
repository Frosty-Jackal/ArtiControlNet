import os
import requests
import cv2
import uuid
from io import BytesIO
import numpy as np
import base64
from PIL import Image


# 增加一个配置项，或者通过环境变量获取
# 如果你在 AutoDL 使用 SSH 隧道映射到本地，保持 localhost:6006 即可
# 如果你使用 AutoDL 的 "自定义服务" 功能，这里需要填公网地址
SERVER_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:6006")


class ImageUtils:
    # 确保输出目录存在
    @staticmethod
    def ensure_directories():
        os.makedirs("static/results", exist_ok=True)

    @staticmethod
    def download_image_from_url(url: str) -> bytes:
        """支持 Base64、URL 和本地路径"""
        if not url:
            raise ValueError("image_url 不能为空")

        # 1. Base64
        if url.startswith("data:image"):
            try:
                _, encoded = url.split(",", 1)
                return base64.b64decode(encoded)
            except Exception as e:
                raise ValueError(f"Base64 解码失败: {e}") from e

        # 2. 本地路径
        if os.path.exists(url):
            with open(url, "rb") as f:
                return f.read()

        # 3. 网络 URL
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content

    # save_image_to_disk 函数可以保留，用于调试，但 Web 流程主要用上面的 image_to_base64
    @staticmethod
    def save_image_to_disk(image_np: np.ndarray, prefix="img") -> str:
        filename = f"{prefix}_{uuid.uuid4()}.png"
        filepath = os.path.join("static", "results", filename)
        img_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
        cv2.imwrite(filepath, img_bgr)
        return filepath

    @staticmethod
    def bytes_to_numpy(image_bytes: bytes) -> np.ndarray:
        pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")
        return np.array(pil_image)

    @staticmethod
    def image_to_base64(image_np: np.ndarray) -> str:
        """
        将 numpy 图片转为 base64 字符串，方便跨网络传输
        """
        # 1. 转为 BGR (OpenCV 格式)
        img_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

        # 2. 编码为 JPG 格式的内存字节流
        _, buffer = cv2.imencode('.jpg', img_bgr)

        # 3. 转为 Base64 字符串
        img_str = base64.b64encode(buffer).decode('utf-8')

        # 4. 拼接前缀
        return f"data:image/jpeg;base64,{img_str}"
