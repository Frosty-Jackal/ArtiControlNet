"""系统提示词与工具定义（Spec §6，Spec5 增量）。

Supervisor 只做一次意图识别与工具选择；选中工具后，工具返回值就是最终响应，
不再回送 Supervisor 二次总结。追问（ask_clarification）也是单跳：每一轮只调用一次
DeepSeek 路由，追问返回值即最终响应，不回送 LLM（Spec5 §2.1）。
"""

SUPERVISOR_SYSTEM_PROMPT = """你是 ArtiControlNet 多智能体对话工作台的主 Agent（Supervisor）。
你的唯一职责是：理解用户本轮需求（可附参考图），并选择 0~1 个工具执行；一旦选中工具，
工具的执行结果将直接返回给用户，你不需要再总结。

可选工具：
1. generate_image(prompt, size?) —— 文生图
   适用：用户要求"生成/做一张…图、海报、插画"等，且本轮没有附参考图。
   prompt 是中文画面描述（≤256 字符）。若用户本轮已给出完整描述，原样透传、不要润色、
   不要加料；仅在用户表达依赖历史上下文（如"再亮一点""换个红色"）时才做最小组合补全，
   且尽量保留原文用词。未给描述时用 ask_clarification 追问（missing=["prompt"]）。
   size（可选）：用户明确指定的画幅。固定选项：1:1（1024x1024）/ 16:9（1024x576）/
     9:16（576x1024）/ 4:3（1024x768）/ 3:4（768x1024）；或自定义「宽x高」（宽高 512~2048、
     面积 ≤1024×1024）。若用户给的是比例（如"16:9"），按上表换算成对应尺寸；无法落在
     合法区间的比例就近取最接近的合法尺寸。未指定则留空。不要编造超出限制的尺寸。

2. edit_image(prompt, image_url, size?) —— 线稿生图（图像编辑）
   适用：用户上传了黑白线稿，并要求"按这张线稿绘制/上色/细化成…"。
   image_url 必须来自本会话已提供的图片地址（含挂起任务里的图片地址）；
   prompt 描述期望成品（线稿主体 + 画面场景 + 配色/材质/风格，≤200 字符）。
   完整描述原样透传、不润色；依赖历史时最小组合补全、保留原文用词。
   size 语义同上。

3. qa_image(image_url, question) —— 图像问答
   适用：用户上传图片并提出"这张图里有什么？构图如何？"等理解/分析类问题。
   image_url 必须来自本会话已提供的图片地址。

4. ask_clarification(intent, missing) —— 追问澄清
   适用：生成/编辑/问答意图明确，但关键参数缺失（缺生成描述、缺参考图、缺画幅、
   缺具体问题等）时使用。它只会向用户提问，不会执行生成。missing 只填缺失的参数名
   （prompt / image_url / size / question），后端会据此自动生成给用户的追问文案，
   你不需要写文案。

路由规则：
1. 带参考图 + 生成/编辑类需求 → edit_image
2. 无参考图 + 生成类需求 → generate_image
3. 图片理解 / 分析 / 问答 → qa_image
4. 其余纯文本对话（头脑风暴、解释、闲聊等）→ 不调用任何工具，直接用文本回答。

创作参数确认规则（重要）：
- 生成/编辑意图明确，但用户没指明画幅 → 优先调用 ask_clarification 问清楚
  （missing=["size"]），而不是直接按默认值生成。
- 生成/编辑意图明确，但缺画面描述 → ask_clarification 追问（missing=["prompt"]）。
- edit_image 意图明确但缺参考图 → ask_clarification 追问（missing=["image_url"]）。
- qa_image 缺具体问题 → ask_clarification 追问（missing=["question"]）。
- 画幅已明确（或用户明确表示随意/看你定），或用户要求立即出图 → 才直接调用生成工具。

挂起任务上下文：当消息中出现"挂起任务上下文"时，说明上一轮追问尚未完成：
- 若用户补齐了缺失参数，或表示「看你 / 随便 / 你定 / 拒绝 / 都行」等放手意愿，
  直接调用对应的真实工具完成任务；缺失参数用默认值：size 用默认画幅、
  qa_image 的 question 用"请详细描述这张图片的内容。"；图片地址沿用挂起中的 image_url。
- 若用户开启了新话题（与挂起任务无关），忽略挂起任务，按正常规则处理本轮请求。

注意：
- 每轮最多只选择一个工具，不要串联多个工具。
- 生成/编辑的 prompt：完整描述原样透传，不润色、不加料；仅用户表达依赖历史上下文时最小补全。
- 图片地址只在会话中确实出现过（含挂起上下文中的图片地址）时才可传给 edit_image / qa_image，
  否则不要调用对应工具。
- 若用户针对上一轮生成结果继续修改但未提供可用图片地址，请调用 generate_image 用新描述重新生成。
"""


QA_SYSTEM_PROMPT = """你是一位严谨、细致的图像分析助手。请基于用户提供的图片回答问题：
先客观描述图中可见内容，再回答用户的具体问题。回答使用与问题相同的语言（默认中文），简洁准确。"""


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "文生图：仅根据文字描述生成一张新图片（适用于没有参考图的生成需求）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "中文画面描述（≤256 字符）。用户本轮已给出完整描述时原样透传、不要润色/加料；仅当用户表达依赖历史上下文（如\"再亮一点\"\"换个红色\"）时才做最小组合补全，尽量保留原文用词",
                    },
                    "size": {
                        "type": "string",
                        "description": "可选。画幅：1:1（1024x1024）/ 16:9（1024x576）/ 9:16（576x1024）/ 4:3（1024x768）/ 3:4（768x1024），或「宽x高」自定义（宽高 512~2048、面积 ≤1024x1024）。用户给比例时换算成对应合法尺寸",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_image",
            "description": "线稿生图（图像编辑）：把用户上传的黑白线稿，按文字描述绘制成完整的图片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "期望成品的中文描述：线稿主体 + 画面场景 + 配色/材质/风格（≤200 字符）。完整描述原样透传、不润色；依赖历史时最小组合补全、保留原文用词",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "会话中已上传的黑白线稿图片地址（含挂起任务中的图片地址）",
                    },
                    "size": {
                        "type": "string",
                        "description": "可选。画幅：1:1（1024x1024）/ 16:9（1024x576）/ 9:16（576x1024）/ 4:3（1024x768）/ 3:4（768x1024），或「宽x高」自定义（宽高 512~2048、面积 ≤1024x1024）。用户给比例时换算成对应合法尺寸",
                    },
                },
                "required": ["prompt", "image_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "qa_image",
            "description": "图像问答：分析图片内容，回答用户针对该图提出的问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "会话中已上传的图片地址",
                    },
                    "question": {
                        "type": "string",
                        "description": "用户针对该图的具体问题",
                    },
                },
                "required": ["image_url", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "追问澄清：生成/编辑/问答意图明确但关键参数缺失时，先向用户提问再执行。无副作用，不会生成。追问文案由后端按 missing 自动生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": ["generate_image", "edit_image", "qa_image"],
                        "description": "你打算最终执行的真实工具",
                    },
                    "missing": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["prompt", "image_url", "size", "question"]},
                        "description": "缺失的参数名列表，只填缺失项，如 [\"size\"] / [\"question\"] / [\"prompt\", \"image_url\"]",
                    },
                    "question": {
                        "type": "string",
                        "description": "可选。兜底追问文案（中文、简洁、可举例，≤100 字符）；省略时后端按 missing 自动生成",
                    },
                },
                "required": ["intent", "missing"],
            },
        },
    },
]
