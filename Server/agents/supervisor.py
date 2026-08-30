"""主 Agent（Supervisor）：单跳路由（Spec §6）。

LangGraph StateGraph：START → router → (tools?) → END
- router 节点：用 DeepSeek 文本模型（支持 Tool Calls）做一次意图识别与工具选择；
- 选中工具 → tools 节点执行对应子 Agent，工具返回值即为最终响应（不回送 LLM）；
- 未选中工具 → router 的文本输出即为最终响应（纯文本对话）。
"""
import logging
from typing import Any, TypedDict

import langgraph.graph as lg

from agents import clarify, editing, generation, qa
from agents.prompts import SUPERVISOR_SYSTEM_PROMPT, TOOL_DEFINITIONS
from errors import AppError, RouterError
from providers import deepseek

logger = logging.getLogger("supervisor")

_graph = None


class AgentState(TypedDict, total=False):
    request: dict
    history: list[dict]
    decision: dict          # {"name": ..., "arguments": {...}}
    result: dict            # {"kind": "text"|"images", ...}


# ---------- 消息拼装 ----------

def _recent_images(history: list[dict], limit: int = 3) -> list[str]:
    refs: list[str] = []
    for item in history:
        if item.get("image_url"):
            refs.append(item["image_url"])
        for u in (item.get("images") or []):
            refs.append(u)
    return refs[-limit:]


def _build_messages(request: dict, history: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT}]
    for item in history:
        role = "user" if item.get("role") == "user" else "assistant"
        text = item.get("text") or item.get("content") or ""
        if not text:
            continue
        messages.append({"role": role, "content": text})
    # 提供近期图片引用，支持多轮图像追问（如"再详细分析这张图"）
    recent = _recent_images(history)
    if recent:
        refs = "\n".join(f"- {u}" for u in recent)
        messages.append({
            "role": "system",
            "content": f"会话中近期出现的图片地址（qa_image/edit_image 可引用）：\n{refs}",
        })
    # 挂起任务上下文（Spec5 §5.2 第二轮）：上一轮追问未完成，本轮回复是其回答或新话题
    pending = request.get("pending")
    if pending:
        missing = pending.get("missing") or []
        missing_line = (f"- 还缺参数：{'、'.join(str(m) for m in missing)}\n"
                        if missing else "")
        messages.append({
            "role": "system",
            "content": (
                "挂起任务上下文：上一轮你发起过一次追问，用户尚未完成。\n"
                f"- 挂起意图（计划工具）：{pending.get('intent') or '未知'}\n"
                f"- 上一轮追问：{pending.get('question') or ''}\n"
                f"{missing_line}"
                f"- 挂起中的图片地址：{pending.get('image_url') or '无'}\n"
                "用户的这条回复是对上述追问的回答，或开启了新话题。请判断：\n"
                "  a. 若用户补齐了缺失参数，或表示「看你/随便/你定/拒绝/都行」等放手意愿\n"
                "     → 直接调用对应的真实工具（generate_image / edit_image / qa_image）完成任务：\n"
                "     缺失的 size 用默认画幅；qa_image 缺失 question 用"
                "「请详细描述这张图片的内容。」；图片地址沿用挂起中的 image_url。\n"
                "  b. 若用户开启了新话题（与挂起任务无关）→ 忽略挂起任务，按正常规则处理本轮请求。"
            ),
        })
    user_msg = (request.get("message") or "").strip()
    if request.get("image_url"):
        user_msg += f"\n[本轮参考图地址: {request['image_url']}]"
    messages.append({"role": "user", "content": user_msg})
    return messages


def _history_text(history: list[dict], limit: int = 6) -> str:
    lines = []
    for item in history[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        text = item.get("text") or item.get("content") or ""
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


# ---------- 节点 ----------

async def router_node(state: AgentState) -> AgentState:
    request = state["request"]
    history = state.get("history") or []
    messages = _build_messages(request, history)
    decision = await deepseek.route_message(messages, TOOL_DEFINITIONS)
    request_id = request.get("request_id", "")
    if decision["kind"] == "tool":
        logger.info(f"选中工具: {decision['name']}", extra={
            "event": "router.decided", "request_id": request_id,
        })
        return {"decision": decision}
    logger.info("纯文本回复", extra={"event": "router.decided",
                                    "request_id": request_id})
    return {"result": {"kind": "text", "text": decision["text"]}}


async def tool_node(state: AgentState) -> AgentState:
    decision = state["decision"]
    name = decision.get("name")
    args = dict(decision.get("arguments") or {})
    request = state["request"]

    # 追问：ask_clarification 是无副作用工具，结果由 worker 转为挂起意图（Spec5 §5.2）。
    # 追问文案由后端按 missing 生成（Spec6 §5.1），missing 一并透传进 pending。
    if name == "ask_clarification":
        image_url = request.get("image_url")
        if not image_url:  # 本轮未带图 → 取会话最近的图片地址
            recent = _recent_images(state.get("history") or [], limit=1)
            image_url = recent[-1] if recent else None
        missing = list(args.get("missing") or [])
        return {"result": {
            "kind": "clarify",
            "intent": args.get("intent"),
            "question": clarify.format_clarify(missing),
            "missing": missing,
            "image_url": image_url,
        }}

    # 注入上下文：站内图片基址 + 近期历史文本（QA 用）+ 作品归属（Spec5 入库）
    args["public_base"] = request.get("public_base", "")
    args["history_text"] = _history_text(state.get("history") or [])
    args["user_id"] = request.get("user_id")

    # 挂起任务的图片地址兜底：用户补全参数时不必再传图（Spec5 §5.5）
    pending = request.get("pending")
    if name in ("edit_image", "qa_image") and not args.get("image_url") and pending:
        args["image_url"] = pending.get("image_url")

    if name == "generate_image":
        result = await generation.run(args)
    elif name == "edit_image":
        result = await editing.run(args)
    elif name == "qa_image":
        result = await qa.run(args)
    else:
        raise RouterError(f"未知工具: {name}")
    # 打上工具标签：子 Agent 返回的 kind 无法区分「文生图/图文生图」（都是 images）
    # 与「对话/图像QA」（都是 text），统计据此归类（Spec4 §2.1）。
    result["tool"] = name
    return {"result": result}


def _decide(state: AgentState) -> str:
    return "tools" if state.get("decision") else "end"


# ---------- 图 ----------

def _build_graph():
    graph = lg.StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router", _decide, {"tools": "tools", "end": lg.END},
    )
    graph.add_edge("tools", lg.END)
    return graph.compile()


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ---------- 入口 ----------

async def run_supervisor(request: dict, history: list[dict],
                         request_id: str = "") -> dict:
    """执行一次单跳路由，返回最终结果 dict（{kind, text?, images?}）。"""
    req = dict(request)
    req["request_id"] = req.get("request_id") or request_id
    initial: AgentState = {"request": req, "history": history or []}
    try:
        final = await _get_graph().ainvoke(initial)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RouterError(f"主 Agent 路由执行失败: {exc}") from exc
    result = final.get("result")
    if not result:
        raise RouterError("主 Agent 未产生结果")
    return result
