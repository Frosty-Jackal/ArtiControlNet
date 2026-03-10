import cv2
import numpy as np
import torch
from annotator.util import HWC3, resize_image
from fastapi.concurrency import run_in_threadpool
from Server.utils import ImageUtils

class ScribbleTool:
    def __init__(self, engine):
        self.engine = engine
        self.config_path = 'models/cldm_v15.yaml'
        self.model_path = 'models/control_sd15_scribble.pth'

    def _preprocess_sync(self, image_np, resolution):
        """
        同步预处理：智能反色 + 噪点清理
        """
        with torch.no_grad():
            # 1. 调整大小
            image_np = resize_image(HWC3(image_np), resolution)
            H, W, C = image_np.shape

            # 2. 灰度化 (为了检测亮度和做二值化)
            # 如果是彩色图(比如手机拍的纸张)，先转灰度
            gray_img = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)

            # 3. 智能判断是否需要反色
            # ControlNet Scribble 需要 "黑底白线"
            # 如果平均亮度 > 127，说明是 "白底黑线" (通常的纸绘)
            if np.mean(gray_img) > 127:
                print("🎨 ScribbleTool: 检测到白底图片，执行反色处理...")
                # 反色：黑底白线
                inverted = 255 - gray_img
            else:
                # 已经是黑底白线，直接用
                inverted = gray_img

            # 4. [关键] 二值化 / 阈值处理
            # 这一步是为了过滤掉纸张的纹理、阴影或不纯的黑色
            # 任何低于 127 的像素变成 0 (纯黑)，高于的变成 255 (纯白)
            # 你可以根据效果调整 127 这个阈值
            _, binary = cv2.threshold(inverted, 127, 255, cv2.THRESH_BINARY)

            # 5. 转回 3 通道 (HWC3)
            detected_map = HWC3(binary)

            # 6. 归一化并转 Tensor
            control = torch.from_numpy(detected_map.copy()).float().cuda() / 255.0

            return detected_map, H, W, C, control

    async def inference(self, request):
        """标准推理入口"""
        try:
            # 1. 下载
            image_data = await run_in_threadpool(ImageUtils.download_image_from_url, request.image_url)
            image_np = await run_in_threadpool(ImageUtils.bytes_to_numpy, image_data)

            # 2. 预处理
            detected_map, H, W, C, control = await run_in_threadpool(
                self._preprocess_sync,
                image_np,
                request.image_resolution
            )

            # 3. 打包参数
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

            # 4. 调用 Engine
            results, used_seed = await self.engine.run_safe_inference(
                config_path=self.config_path,
                model_path=self.model_path,
                inference_args=inference_args
            )

            # 5. 保存
            output_data = []
            for img_array in results:
                # 核心：转成 Base64 字符串
                b64 = ImageUtils.image_to_base64(img_array)
                output_data.append(b64)

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