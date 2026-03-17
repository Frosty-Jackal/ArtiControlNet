import torch
import random
import einops
import numpy as np
import config
import gc
import asyncio

from pytorch_lightning import seed_everything
from cldm.model import create_model, load_state_dict
from cldm.ddim_hacked import DDIMSampler
from fastapi.concurrency import run_in_threadpool # 引入 FastAPI 的线程池工具
class StableDiffusionEngine:
    """
    负责加载模型和执行核心的 Diffusion 推理。
    这个类应该是单例的，或者由 Manager 管理，以避免重复加载模型。
    增加了显存管理机制，支持动态切换模型而不爆显存。
    """
    # 初始化模型
    # 1. 载入结构 2. 载入权重 3. 移至GPU 4.设置为推理模式
    def __init__(self):
        # 初始化时不加载模型，只初始化变量
        self.model = None
        self.ddim_sampler = None
        self.current_model_path = None
        self.current_config_path = None
        # 创建一个异步锁
        # 这把锁保证同一时间只有一个请求能操作GPU
        self.lock = None



    def switch_model(self, config_path, model_path):
        """
        动态切换模型的核心函数。
        如果目标模型已加载，则跳过；否则卸载旧模型，清理显存，加载新模型。
        """
        #检查是否需要切换
        if self.model is not None and self.current_model_path == model_path:
            print(f"Model {model_path} is already loaded. Skipping reload.")
            return
        print(f"Switching model to {model_path}...")

        #卸载旧模型并清理显存
        if self.model is not None:
            self.model.cpu()
            del self.model
            del self.ddim_sampler
            self.model = None
            self.ddim_sampler = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # 3. 加载新模型
        try:
            self.model = create_model(config_path).cpu()
            self.model.load_state_dict(load_state_dict(model_path, location=device))
            self.model = self.model.to(device)
            self.model.eval()
            self.ddim_sampler = DDIMSampler(self.model)

            if config.save_memory and device == "cuda":
                self.model.low_vram_shift(is_diffusing=False)

            # 更新当前状态
            self.current_model_path = model_path
            self.current_config_path = config_path
            print(f"Model {model_path} loaded successfully!")

        except Exception as e:
            print(f"Failed to load model: {e}")
            raise e

    def process(
            self,detected_map, H, W, C, control,
            prompt, a_prompt, n_prompt, num_samples,
            ddim_steps, guess_mode, strength, scale, seed, eta
    ):
        """通用推理逻辑"""
        if self.model is None:
            raise RuntimeError("Model not loaded! Please call 'switch_model' first.")

        # 限制参数上限，防止OOM(显存溢出)
        num_samples = min(max(num_samples, 1), 4)
        ddim_steps = min(max(ddim_steps, 1), 50)

        with torch.no_grad():
            # 准备控制张量
            # 添加批次维度

            # 1. 确保 control 图片在 GPU
            if isinstance(control, np.ndarray):
                control = torch.from_numpy(control.copy())
            if torch.cuda.is_available():
                control = control.cuda()

            control = control.float() / 255.0
            control = torch.stack([control for _ in range(num_samples)], dim=0)
            control = einops.rearrange(control, 'b h w c -> b c h w').clone()

            # 设置随机种子
            if seed == -1:
                seed = random.randint(0, 65535)
            seed_everything(seed)

            if config.save_memory and torch.cuda.is_available():
                self.model.low_vram_shift(is_diffusing=False)

             # 获取条件向量 (Prompt)
            cond_crossattn = self.model.get_learned_conditioning([prompt + ', ' + a_prompt] * num_samples)
            # 获取无条件向量 (Negative Prompt)
            un_cond_crossattn = self.model.get_learned_conditioning([n_prompt] * num_samples)

            # 无论它们是在 CPU 还是 GPU 生成的，统统搬到 CUDA！
            if torch.cuda.is_available():
                cond_crossattn = cond_crossattn.cuda()
                un_cond_crossattn = un_cond_crossattn.cuda()

            # 组装条件字典
            cond = {
                "c_concat": [control],
                "c_crossattn": [cond_crossattn]
            }
            un_cond = {
                "c_concat": None if guess_mode else [control],
                "c_crossattn": [un_cond_crossattn]
            }
            shape = (4, H // 8, W // 8)

            # 无论 save_memory 开没开，这最后一步强制检查
            # 确保 UNet (model.model) 和 ControlNet (model.control_model) 都在 GPU 上
            if torch.cuda.is_available():
                try:
                    # 尝试强制移动关键组件，防止 low_vram_shift 失效
                    self.model.model.cuda()
                    self.model.control_model.cuda()
                except Exception:
                    # 如果结构不同，退回到整体移动
                    self.model.cuda()

            # 设置控制强度
            self.model.control_scales = [strength * (0.825 ** float(12 - i)) for i in range(13)] if guess_mode else (
                    [strength] * 13)
            # 采样
            samples, intermediates = self.ddim_sampler.sample(ddim_steps, num_samples,
                                                         shape, cond, verbose=False, eta=eta,
                                                         unconditional_guidance_scale=scale,
                                                         unconditional_conditioning=un_cond)
            if config.save_memory and torch.cuda.is_available():
                self.model.low_vram_shift(is_diffusing=False)

            # 解码
            x_samples = self.model.decode_first_stage(samples)
            # VAE decoder 转成像素空间，最后转成 uint8 的 [0,255] 图片数组
            x_samples = (einops.rearrange(x_samples, 'b c h w -> b h w c')
                         * 127.5 + 127.5).cpu().numpy().clip(0, 255).astype(np.uint8)
            results = [x_samples[i] for i in range(num_samples)]

        return [detected_map] + results,seed  # 返回边缘图+生成图

    #新增一个“安全入口”
    async def run_safe_inference(self, config_path, model_path, inference_args):
        """
        对外暴露的唯一安全入口。
        功能：获取锁 -> (切换模型 + 推理) -> 释放锁
        """
        #懒加载锁：确保 Lock 是在当前的 Uvicorn Event Loop 中创建的
        if self.lock is None:
            self.lock = asyncio.Lock()

        # 获取锁：如果此时有人在用 GPU，这里会等待
        async with self.lock:
            # 切换模型
            await run_in_threadpool(self.switch_model, config_path, model_path)

            # 执行推理
            result = await run_in_threadpool(
                self.process,
                **inference_args
            )
            return result

