import os
import uvicorn
import requests
import uuid
import tempfile
import base64

from typing import List, Optional, Dict, Any, Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# LangChain / LangGraph 相关导入
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 1. 配置部分

# 你的 ControlNet 画图服务地址 (端口 6006)
CANNY_API_URL = "http://localhost:6006/api/controlnet/generate_canny"
SCRIBBLE_API_URL = "http://localhost:6006/api/controlnet/generate_scribble"

# 设置 API Key (你的 DeepSeek Key)
os.environ["OPENAI_API_KEY"] = "sk-33b4f0d880454dcbbadb453e79d0717e"


# 2. 定义工具 (Tools)
# 辅助函数：读取本地文件转 Base64 (给工具用的)
def local_image_to_base64(image_path: str) -> str:
    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        return f"data:image/jpeg;base64,{encoded_string}"
    except Exception as e:
        print(f"读取临时文件失败: {e}")
        return image_path # 如果读取失败，原样返回试试

# 辅助函数 专门用来清洗后端返回数据的函数
def save_backend_image_to_local(base64_data: str, prefix: str) -> str:
    """
    将后端返回的 Base64 图片保存为本地文件，防止撑爆 LLM 上下文。
    """
    try:
        # 如果数据很短（比如已经是 URL 了），就不用管
        if len(base64_data) < 500:
            return base64_data

        # 清洗前缀 (data:image/png;base64,...)
        if "base64," in base64_data:
            _, encoded = base64_data.split("base64,", 1)
        else:
            encoded = base64_data

        image_data = base64.b64decode(encoded)

        # 保存到临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", mode="wb", prefix=prefix) as tmp:
            tmp.write(image_data)
            saved_path = tmp.name

        print(f"[出口清洗] 后端返回的大图已转存至: {saved_path}")
        return saved_path
    except Exception as e:
        print(f"图片转存失败: {e}")
        return "(图片保存失败)"



@tool
def generate_canny_image(prompt: str, image_url: str, strength: float = 1.0) -> str:
    """
    当用户想要基于线稿或参考图生成新图片时使用此工具。
    Args:
        prompt: 图片的详细英文描述.
        image_url: 图片路径 (例如 /tmp/xxx.jpg) 或者 URL
        strength: 控制强度 (0.0-2.0).
    """
    print(f"Agent 调用 Canny 工具: {prompt}")

    # 如果 LLM 传给我们的是本地临时路径，我们需要读出来转 Base64 发给后端
    # 这样后端无论是本地还是远程都能收到图
    final_image_data = image_url
    if os.path.exists(image_url):
        print("工具正在读取本地临时文件并打包...")
        final_image_data = local_image_to_base64(image_url)


    payload = {"prompt": prompt, "image_url": final_image_data, "strength": strength}
    try:
        response = requests.post(CANNY_API_URL, json=payload, timeout=360)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            # 绝对不能直接把 data 返回给 LLM！必须先存盘！
            edge_path = save_backend_image_to_local(data['edge_map_url'], "edge_")
            gen_path = save_backend_image_to_local(data['generated_image_url'], "final_")

            # 只返回短路径，LLM 看了很开心
            return f"生成成功！\n边缘参考图: {edge_path}\n最终成图: {gen_path}"
        else:
            return f"API 返回错误: {data}"
    except Exception as e:
        return f"调用工具失败: {str(e)}"


@tool
def generate_scribble_image(prompt: str, image_url: str, strength: float = 1.0) -> str:
    """
    当用户上传了一张【手绘草图】、【涂鸦】或者【简笔画】时，使用此工具。
    Args:
        image_url: 图片路径 (例如 /tmp/xxx.jpg) 或者 URL
    """
    print(f"Agent 调用 Scribble 工具，图片路径: {image_url[:50]}...")

    final_image_data = image_url
    if os.path.exists(image_url):
        print("Scribble工具: 正在读取本地临时文件并打包...")
        final_image_data = local_image_to_base64(image_url)

    payload = {"prompt": prompt, "image_url": final_image_data, "strength": strength}
    try:
        response = requests.post(SCRIBBLE_API_URL, json=payload, timeout=360)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            edge_path = save_backend_image_to_local(data['edge_map_url'], "edge_scribble_")
            gen_path = save_backend_image_to_local(data['generated_image_url'], "final_scribble_")

            return f"涂鸦生成成功！\n线稿: {edge_path}\n最终成图: {gen_path}"
        else:
            return f"生成失败: {data}"
    except Exception as e:
        return f"Scribble工具调用异常: {str(e)}"


# 工具列表
tools = [generate_canny_image, generate_scribble_image]


# 3. 构建 Agent 图 (Graph)

# 初始化 LLM (DeepSeek)
llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.7,
    base_url="https://api.deepseek.com",
)
llm_with_tools = llm.bind_tools(tools)


# 定义状态
class State(TypedDict):
    messages: Annotated[List, add_messages]


# 定义思考节点
def reasoner(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}


# 构建图
builder = StateGraph(State)
builder.add_node("agent", reasoner)
builder.add_node("tools", ToolNode(tools))

builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")

# 编译图
agent_app = builder.compile()

# 4. FastAPI 服务端代码

app = FastAPI(title="Agent Chat Server")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 定义数据模型
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    image_url: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    thread_id: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    # 1. 准备 thread_id
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    user_content = request.message
    system_instruction = ""  # 用于存放关于图片的特殊指令

    # 2. 处理图片逻辑
    if request.image_url:
        # 只要 URL 长度超过 500，或者包含 base64 标记，就认定为图片数据
        if len(request.image_url) > 500 or "base64" in request.image_url:
            print(f"检测到超长图片数据 (长度: {len(request.image_url)})，正在拦截...")
            try:
                # 尝试分割前缀 (例如 data:image/png;base64,...)
                if "," in request.image_url:
                    _, encoded = request.image_url.split(",", 1)
                else:
                    encoded = request.image_url

                # 解码并保存
                image_data = base64.b64decode(encoded)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png", mode="wb") as tmp:
                    tmp.write(image_data)
                    temp_path = tmp.name

                print(f"图片已暂存至本地: {temp_path}")

                # 关键：只给 LLM 看路径，绝对不给它看 Base64
                user_content += f"\n(系统提示：用户上传了一张参考图片，已自动保存到本地路径: {temp_path}。请直接将此路径传给工具函数，不要索要 URL)"

            except Exception as e:
                print(f"图片处理失败: {e}")
                user_content += "\n(图片上传处理失败)"
        else:
            # 如果是正常的短链接 (http://... 或 /tmp/...)
            user_content += f"\n(附带参考图路径: {request.image_url})"

        # [最后一道防线] 再次检查 prompt 长度
        # 如果因为某种原因 Base64 还是漏进去了，这里强行截断，防止 LLM 报错
    if len(user_content) > 30000:
        print("警告：Prompt 依然过长，触发熔断截断！")
        user_content = user_content[:2000] + "\n...(内容过长已截断)"


    # 3. 增强 System Prompt
    # 这一步是为了防止 LLM “装傻”，强行告诉它本地路径是可用的
    system_prompt = """
    你是一个精通 AI 绘图的助手。

    【重要规则】
    1. 当你在用户输入中看到【系统提示：用户上传了一张参考图片...】时，说明用户已经提供了图片。
    2. 你**必须**直接提取该路径，并根据用户的需求调用 generate_canny_image 或 generate_scribble_image 工具。
    3. **绝对不要** 再问用户“请提供图片路径”或“请上传图片”，因为图片就在你面前！
    4. 如果用户只发了图片没说话，默认推测用户想把这张图变成“赛博朋克”或“精美二次元”风格。
    
    【核心展示规则】
    5. 当工具执行成功并返回图片 URL 时，你**必须**使用 Markdown 格式输出图片，以便用户能直接看到。
       格式要求：![生成图片](图片URL)
       例如：![result](http://localhost:6006/static/output.png)
    """

    # 4. 构造消息列表
    # 使用 SystemMessage + HumanMessage 的组合
    input_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]

    print(f"最终发送给 LLM 的 Prompt:\n{user_content}")  # 调试打印，看看路径到底有没有拼进去

    try:
        # 5. 运行 Agent
        final_state = await agent_app.ainvoke({"messages": input_messages}, config=config)

        # 6. 提取回复
        last_message = final_state["messages"][-1]
        response_text = last_message.content

        return ChatResponse(
            response=response_text,
            thread_id=thread_id
        )

    except Exception as e:
        print(f"Agent 运行出错: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # 启动服务，运行在 8000 端口
    print("Agent Server 正在启动，监听端口 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)



