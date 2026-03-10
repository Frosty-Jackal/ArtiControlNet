from pydantic import BaseModel, Field


# 定义请求体：这是给 LLM 看的“说明书”
# Agent 发过来的是 JSON 数据包，FastAPI 会自动把 JSON 映射到这个 Pydantic 类中
class ControlNetRequest(BaseModel):
    prompt: str = Field(..., description="图片的英文描述，包括风格、主体、细节等")
    image_url: str = Field(..., description="输入图片的 URL 地址 (Agent 会传入上一步生成的图或用户提供的图)")
    # 选填参数给默认值，减少 LLM 的决策负担
    strength: float = Field(1.0,description="控制强度 (Control Strength)。范围 0.0-2.0。"
                                            "1.0 代表严格遵循线条，0.5 代表仅参考轮廓结构。"
    )
    low_threshold: int = Field(100,description="Canny 边缘检测低阈值。数值越低，检测到的线条细节越多（适合草图）；"
                                               "数值越高，线条越少（适合轮廓）。"
    )
    high_threshold: int = Field(200,description="Canny 边缘检测高阈值。通常设置为低阈值的2倍。"
    )
    seed: int = Field(-1,description="随机种子。-1 代表随机。如果用户想要'保持构图不变微调'，请传入固定的种子。"
    )
    #高级默认项
    image_resolution: int = Field(512, description="生成图像的分辨率")
    num_samples: int = Field(1, description="一次生成的图片数量")
    ddim_steps: int = Field(20, description="采样步数，推荐 20-30")
    scale: float = Field(9.0, description="CFG Scale (提示词引导系数)")
    eta: float = Field(0.0, description="DDIM eta")
    # 提示词优化，硬编码默认值
    a_prompt: str = Field(
        "best quality, extremely detailed",
        description="质量增强提示词 (Hidden)"
    )
    n_prompt: str = Field(
        "longbody, lowres, bad anatomy, bad hands, missing fingers,"
        " extra digit, fewer digits, cropped, worst quality, low quality",
        description="负向提示词 (Hidden)"
    )
    guess_mode: bool = Field(False, description="猜测模式")
