from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from typing import Annotated, List, TypedDict, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode, tools_condition
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
import os
# 统一 API Key 配置

if OPENAI_API_KEY and "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# 定义路由工具
@tool
def call_image_agent(message: str, image_url: str = None) -> str:
    """当用户需要图片处理（线稿提取、涂鸦生成等）时调用此工具"""
    from agent_image import process_image_request
    return process_image_request(message, image_url)

@tool
def call_text_agent(message: str) -> str:
    """当用户需要文本处理、问答、翻译等时调用此工具"""
    # 先给最小可用版，别再返回占位符
    return f"文本请求收到：{message}"

# 路由Agent的LLM
router_llm = ChatOpenAI(
    model=MODEL_NAME,
    temperature=0.3,
    base_url=OPENAI_BASE_URL,
)

# 路由Agent的系统提示
ROUTER_SYSTEM_PROMPT = """
你是一个智能路由助手，负责判断用户请求应该由哪个专业Agent处理。

【路由规则】
1. 图片处理请求（线稿、涂鸦、风格转换、参考图生成）→ 调用 call_image_agent
2. 文本处理请求（问答、翻译、总结）→ 调用 call_text_agent  
3. 如果请求涉及多个领域，优先调用最相关的Agent

【重要】
- 如果用户上传了图片，优先判断是否需要图片处理
- 不要直接回答用户问题，而是调用合适的工具
"""

# 构建路由图
router_tools = [call_image_agent, call_text_agent]
router_llm_with_tools = router_llm.bind_tools(router_tools)

class RouterState(TypedDict):
    messages: Annotated[List, add_messages]
    thread_id: Optional[str]
    image_url: Optional[str]

def router_node(state: RouterState):
    # 把 thread_id / image_url 明确注入到消息上下文，降低丢参概率
    context_msg = (
        f"[上下文]\n"
        f"thread_id={state.get('thread_id')}\n"
        f"image_url={state.get('image_url')}\n"
    )
    msgs = list(state["messages"])
    msgs[0].content = msgs[0].content + "\n\n" + context_msg
    return {"messages": [router_llm_with_tools.invoke(msgs)]}


router_builder = StateGraph(RouterState)
router_builder.add_node("router", router_node)
router_builder.add_node("tools", ToolNode(router_tools))
router_builder.add_edge(START, "router")
router_builder.add_conditional_edges("router", tools_condition)
router_builder.add_edge("tools", "router")
router_app = router_builder.compile()