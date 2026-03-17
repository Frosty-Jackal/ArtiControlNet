# config.py
import os
from pathlib import Path

save_memory = False

# API 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-33b4f0d880454dcbbadb453e79d0717e")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

# 服务配置
MAIN_SERVER_HOST = os.getenv("MAIN_SERVER_HOST", "0.0.0.0")
MAIN_SERVER_PORT = int(os.getenv("MAIN_SERVER_PORT", "8000"))
CONTROLNET_SERVER_PORT = int(os.getenv("CONTROLNET_SERVER_PORT", "6006"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "7860"))

# 文件配置
BASE_DIR = Path(__file__).parent
TMP_IMAGES_DIR = BASE_DIR / "tmp_images"
TMP_IMAGES_DIR.mkdir(exist_ok=True)

# URL 配置
SERVER_URL = os.getenv("SERVER_URL", f"http://localhost:{MAIN_SERVER_PORT}")

if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

__all__ = [
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL_NAME", "TEMPERATURE",
    "MAIN_SERVER_HOST", "MAIN_SERVER_PORT", "CONTROLNET_SERVER_PORT", "FRONTEND_PORT",
    "TMP_IMAGES_DIR", "SERVER_URL", "BASE_DIR", "save_memory"
]