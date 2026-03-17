import os
import uvicorn
import requests
import uuid
import tempfile
import base64
from config import TMP_IMAGES_DIR, SERVER_URL, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from typing import List, Optional, Dict, Any, Annotated
import re
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
if "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


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
    try:
        if not base64_data:
            raise ValueError("空图片数据")

        if len(base64_data) < 500 and os.path.exists(base64_data):
            return base64_data

        if "base64," in base64_data:
            _, encoded = base64_data.split("base64,", 1)
        else:
            encoded = base64_data

        image_data = base64.b64decode(encoded)

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".png",
            mode="wb",
            prefix=prefix,
            dir=str(TMP_IMAGES_DIR)
        ) as tmp:
            tmp.write(image_data)
            return tmp.name
    except Exception as e:
        print(f"图片转存失败: {e}")
        return "(图片保存失败)"


def local_path_to_public_url(path: str) -> str:
    if path and os.path.exists(path):
        filename = os.path.basename(path)
        return f"{SERVER_URL}/images/{filename}"
    return path



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

    if not image_url:
        return "缺少参考图，无法执行 Canny 生成。"

    # 如果 LLM 传给我们的是本地临时路径，我们需要读出来转 Base64 发给后端
    # 这样后端无论是本地还是远程都能收到图
    final_image_data = image_url
    if os.path.exists(image_url):
        print("工具正在读取本地临时文件并打包...")
        final_image_data = local_image_to_base64(image_url)


    payload = {"prompt": prompt, "image_url": final_image_data, "strength": strength}
    response = requests.post(CANNY_API_URL, json=payload, timeout=360)
    try:

        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            # 绝对不能直接把 data 返回给 LLM！必须先存盘！
            edge_path = save_backend_image_to_local(data['edge_map_url'], "edge_")
            gen_path = save_backend_image_to_local(data['generated_image_url'], "final_")

            edge_url = local_path_to_public_url(edge_path)
            gen_url = local_path_to_public_url(gen_path)

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

    if not image_url:
        return "缺少参考图，无法执行 Scribble 生成。"

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

            edge_url = local_path_to_public_url(edge_path)
            gen_url = local_path_to_public_url(gen_path)

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
    model=MODEL_NAME,
    temperature=0.7,
    base_url=OPENAI_BASE_URL,
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


def process_image_request(message: str, image_url: str = None, thread_id: str = None) -> str:
    """
    供 router_agent 调用的图片处理入口
    """
    import uuid
    from langchain_core.messages import HumanMessage, SystemMessage

    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 构建系统提示（复用现有的）
    system_prompt = """
       你是一个精通 AI 绘图的助手。
       如果用户已经提供参考图，你必须直接根据用户需求调用 generate_canny_image 或 generate_scribble_image。
       不要要求用户再次上传图片。
       工具返回结果后，直接整理成自然语言回复即可。
       """

    # 处理图片逻辑
    user_content = message
    if image_url:
        user_content += f"\n参考图路径: {image_url}"

    input_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]

    # 调用现有的 agent_app
    final_state = agent_app.invoke({"messages": input_messages}, config=config)
    response_text = final_state["messages"][-1].content

    return response_text









