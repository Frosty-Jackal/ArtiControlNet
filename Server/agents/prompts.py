"""系统提示词与工具定义（Spec §6）。

Supervisor 只做一次意图识别与工具选择；选中工具后，工具返回值就是最终响应，
不再回送 Supervisor 二次总结。
"""

SUPERVISOR_SYSTEM_PROMPT = """你是 ArtiControlNet 多智能体对话工作台的主 Agent（Supervisor）。
你的唯一职责是：理解用户本轮需求（可附参考图），并选择 0~1 个工具执行；一旦选中工具，
工具的执行结果将直接返回给用户，你不需要再总结。

可选工具：
1. generate_image(prompt) —— 文生图
   适用：用户要求"生成/做一张…图、海报、插画"等，且本轮没有附参考图。
   prompt 必须是完整、独立的中文画面描述（≤256 字符），综合对话历史补全，
   例如把"再亮一点""换个红色"改写为完整的画面描述。

2. edit_image(prompt, image_url) —— 线稿生图（图像编辑）
   适用：用户上传了黑白线稿，并要求"按这张线稿绘制/上色/细化成…"。
   image_url 必须来自本会话已提供的图片地址；prompt 描述期望成品
   （线稿主体 + 画面场景 + 配色/材质/风格，≤200 字符）。

3. qa_image(image_url, question) —— 图像问答
   适用：用户上传图片并提出"这张图里有什么？构图如何？"等理解/分析类问题。
   image_url 必须来自本会话已提供的图片地址。

路由规则：
1. 带参考图 + 生成/编辑类需求 → edit_image
2. 无参考图 + 生成类需求 → generate_image
3. 图片理解 / 分析 / 问答 → qa_image
4. 其余纯文本对话（头脑风暴、解释、闲聊等）→ 不调用任何工具，直接用文本回答。

注意：
- 每轮最多只选择一个工具，不要串联多个工具。
- 生成/编辑的 prompt 请综合对话历史，补全成独立、可执行的中文描述。
- 图片地址只在会话中确实出现过时才可传给 edit_image / qa_image，否则不要调用对应工具。
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
                        "description": "完整、独立的中文画面描述，≤256 字符，综合对话历史补全",
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
                        "description": "期望成品的中文描述：线稿主体 + 画面场景 + 配色/材质/风格，≤200 字符",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "会话中已上传的黑白线稿图片地址",
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
]
