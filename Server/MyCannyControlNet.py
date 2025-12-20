import io
import base64
import numpy as np
import torch
import random
import config
import einops
import cv2
import uvicorn  #用于启动服务器
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from pytorch_lightning import seed_everything
from fastapi.middleware.cors import CORSMiddleware
from annotator.util import resize_image, HWC3
from annotator.canny import CannyDetector
from cldm.model import create_model, load_state_dict
from cldm.ddim_hacked import DDIMSampler
from PIL import Image

app = FastAPI(title="ControlNet API")

#解决跨域问题，允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
#将 numpy 数组转换为前端可识别的 Base64 字符串
def numpy_to_base64(img_array):
    #注意：Stable Diffusion 输出通常是 RGB，而 OpenCV 默认 BGR
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    _, buffer = cv2.imencode('.png', img_bgr)
    img_str = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/png;base64,{img_str}"

apply_canny=CannyDetector()

#初始化模型
# 1. 载入结构 2. 载入权重 3. 移至GPU 4.设置为推理模式
def initialize_models():
    model = create_model('../models/cldm_v15.yaml').cpu()
    model.load_state_dict(load_state_dict('../models/control_sd15_canny.pth', location='cuda'))
    model = model.cuda()
    model.eval() #固定推理行为
    ddim_sampler = DDIMSampler(model)
    model.low_vram_shift(is_diffusing=False)
    return model, ddim_sampler

#全局模型实例
model, ddim_sampler = initialize_models()

#图片预处理
def image_process(
    image_data: bytes,
    image_resolution: int = 512,
    low_threshold: int = 100,
    high_threshold: int = 200
):
    with torch.no_grad():
        # 读取图片
        image = Image.open(io.BytesIO(image_data))
        # 转换为RGB
        if image.mode != 'RGB':
            image = image.convert('RGB')
        # 转换为numpy数组
        image_np = np.array(image)

        #调整图片大小
        image_np = resize_image(HWC3(image_np), image_resolution)
        H, W, C = image_np.shape

        #Canny边缘检测
        detected_map = apply_canny(image_np, low_threshold, high_threshold)
        detected_map = HWC3(detected_map)# 确保是三通道

        #准备控制张量
        control = torch.from_numpy(detected_map.copy()).float().cuda() / 255.0

        return detected_map, H, W, C, control

def process(
    detected_map, H, W, C, control,
    prompt, a_prompt, n_prompt, num_samples,
    ddim_steps, guess_mode, strength, scale, seed, eta
):
    # 限制参数上限，防止OOM(显存溢出)
    num_samples = min(max(num_samples, 1), 4)
    ddim_steps = min(max(ddim_steps, 1), 50)

    with torch.no_grad():
        #准备控制张量
        #添加批次维度
        control = torch.stack([control for _ in range(num_samples)], dim=0)
        control = einops.rearrange(control, 'b h w c -> b c h w').clone()

        # 设置随机种子
        if seed == -1:
            seed = random.randint(0, 65535)
        seed_everything(seed)

        if config.save_memory:
            model.low_vram_shift(is_diffusing=False)

        # 准备条件
        cond = {"c_concat": [control],"c_crossattn": [model.get_learned_conditioning([prompt + ', ' + a_prompt] * num_samples)]}
        un_cond = {"c_concat": None if guess_mode else [control],"c_crossattn": [model.get_learned_conditioning([n_prompt] * num_samples)]}
        shape = (4, H // 8, W // 8)

        if config.save_memory:
            model.low_vram_shift(is_diffusing=True)

        # 设置控制强度
        model.control_scales = [strength * (0.825 ** float(12 - i)) for i in range(13)] if guess_mode else (
                    [strength] * 13)
        # 采样
        samples, intermediates = ddim_sampler.sample(ddim_steps, num_samples,
                                                     shape, cond, verbose=False, eta=eta,
                                                     unconditional_guidance_scale=scale,
                                                     unconditional_conditioning=un_cond)
        if config.save_memory:
            model.low_vram_shift(is_diffusing=False)

        # 解码
        x_samples = model.decode_first_stage(samples)
        #VAE decoder 转成像素空间，最后转成 uint8 的 [0,255] 图片数组
        x_samples = (einops.rearrange(x_samples, 'b c h w -> b h w c') * 127.5 + 127.5).cpu().numpy().clip(0,255).astype(np.uint8)

        results = [x_samples[i] for i in range(num_samples)]

    return [detected_map] + results # 返回边缘图+生成图





@app.post("/api/controlnet/generate_canny")
async def controlnet_generate_canny(
    #图片参数
    image: UploadFile = File(...,description="输入图片"),

    #文本参数，主体描述
    prompt: str = Form(...,description="提示词"),

    #添加其他必要参数
        #附加的“质量增强”正向提示
        a_prompt: str = Form("best quality, extremely detailed"),
        #负向提示（避免畸形手、低质量等）
        n_prompt: str = Form("longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality"),
        #一次生成多少张
        num_samples: int = Form(1),
        #输入图 resize 的目标分辨率（影响效果与显存）
        image_resolution: int = Form(512),
        #采样步数（越多通常越细致但越慢）
        ddim_steps: int = Form(20),
        #ControlNet“猜测模式”，控制逐层衰减，条件约束更弱
        guess_mode: bool = Form(False),
        #ControlNet 控制强度（越大越贴边缘）
        strength: float = Form(1.0),
        #CFG guidance scale（越大越听 prompt，但过大可能出现过饱和/崩坏）
        scale: float = Form(9.0),
        #随机种子（-1 表示随机）
        seed: int = Form(-1),
        #DDIM 的随机性参数（0 更确定性，>0 更随机）
        eta: float = Form(0.0),
        #low_threshold/high_threshold：Canny 阈值，决定边缘密度
        low_threshold: int = Form(100),
        high_threshold: int = Form(200),

):
    try:
        image_data =await image.read()

        # 预处理图片
        detected_map, H, W, C, control = image_process(
            image_data,
            image_resolution=image_resolution,
            low_threshold=low_threshold,
            high_threshold=high_threshold
        )

        #调用process函数,推理
        results = process(detected_map=detected_map,H=H, W=W, C=C,control=control,prompt=prompt,a_prompt=a_prompt,
            n_prompt=n_prompt,num_samples=num_samples,ddim_steps=ddim_steps,guess_mode=guess_mode,strength=strength,scale=scale,seed=seed,
            eta=eta
        )

        #转换为 Base64 列表
        images=[numpy_to_base64(img)for img in results]

        # 转换并返回结果
        return {
            "status": "success",
            "images": images,
            "info": {"seed": seed, "size": [W, H]}
        }
    except Exception as ex:
        # 这里的异常捕获会返回给前端具体的错误信息
        raise HTTPException(status_code=500, detail=str(ex))


#启动逻辑
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    




