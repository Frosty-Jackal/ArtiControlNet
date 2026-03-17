import io
import torch
import numpy as np
import os

from PIL import Image
from fastapi.concurrency import run_in_threadpool
from annotator.canny import CannyDetector
from annotator.util import HWC3, resize_image
from pathlib import Path

# 引入兄弟模块
from Server.utils import ImageUtils
from Server.schemas import ControlNetRequest
from Server.StableDiffusionEngine import StableDiffusionEngine



class CannyTool:
    """
    专门处理 Canny 逻辑的工具类。
    """
    def __init__(self, engine: StableDiffusionEngine):
        self.engine = engine
        self.detector = CannyDetector()
        # 定义该工具需要的模型路径
        project_root = Path(__file__).resolve().parents[2]
        models_dir = project_root / "models"

        self.config_path = str(models_dir / "cldm_v15.yaml")
        self.model_path = str(models_dir / "control_sd15_canny.pth")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"找不到配置文件: {self.config_path}")
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"找不到模型权重: {self.model_path}")

    # 图片预处理
    def image_process(
            self,
            image_np,
            image_resolution: int = 512,
            low_threshold: int = 100,
            high_threshold: int = 200
    ):
        with torch.no_grad():
            # 调整图片大小
            image_np = resize_image(HWC3(image_np), image_resolution)
            H, W, C = image_np.shape

            # Canny边缘检测
            detected_map = self.detector(image_np, low_threshold, high_threshold)
            detected_map = HWC3(detected_map)  # 确保是三通道

            # 准备控制张量
            control = torch.from_numpy(detected_map.copy()).float()
            return detected_map, H, W, C, control

    async def inference(self,request: ControlNetRequest):
        """对外暴露的统一推理入口"""
        try:
            # 异步下载/读取图片(不阻塞主线程)
            image_data = await run_in_threadpool(ImageUtils.download_image_from_url,
                                                 request.image_url)
            image_np = await run_in_threadpool(ImageUtils.bytes_to_numpy, image_data)

            # 预处理图片
            detected_map, H, W, C, control = await run_in_threadpool(
                self.image_process,
                image_np,
                request.image_resolution,
                request.low_threshold,
                request.high_threshold
            )

            # 由于这是同步代码，使用 run_in_threadpool 防止阻塞
            await run_in_threadpool(
                self.engine.switch_model,
                self.config_path,
                self.model_path
            )

            # 准备推理参数字典
            #将所有 Engine.process 需要的参数打包
            inference_args = {
                "detected_map": detected_map,
                "H": H, "W": W, "C": C,
                "control": control,
                "prompt": request.prompt,
                "a_prompt": request.a_prompt,
                "n_prompt": request.n_prompt,
                "num_samples": request.num_samples,
                "ddim_steps": request.ddim_steps,
                "guess_mode": request.guess_mode,
                "strength": request.strength,
                "scale": request.scale,
                "seed": request.seed,
                "eta": request.eta
            }
            # 这一步会自动处理：获取锁 -> 切换模型 -> 推理 -> 释放锁
            # 且全程在线程池中运行，不会阻塞 FastAPI 主线程
            results, used_seed = await self.engine.run_safe_inference(
                config_path=self.config_path,
                model_path=self.model_path,
                inference_args=inference_args
            )

            # results[0] 是 Canny 边缘图，results[1:] 是生成的图
            # 我们通常希望 Agent 既能看到边缘图(调试用)，也能看到结果图

            # 直接转 Base64
            output_data = [ImageUtils.image_to_base64(img_array) for img_array in results]

            return {
                "status": "success",
                # 直接返回 Base64 数据
                "edge_map_url": output_data[0],
                "generated_image_url": output_data[1],
                "info": {"seed": used_seed}
            }
        except Exception as ex:
            import traceback
            traceback.print_exc()
            raise ex


