from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uuid
import tempfile
import base64
import os

from langchain_core.messages import HumanMessage, SystemMessage
from router_agent import router_app, ROUTER_SYSTEM_PROMPT
from config import TMP_IMAGES_DIR, SERVER_URL, MAIN_SERVER_HOST, MAIN_SERVER_PORT


app = FastAPI()

# 添加跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/images", StaticFiles(directory=str(TMP_IMAGES_DIR)), name="images")


class ChatRequest(BaseModel):
    message: str
    image_url: Optional[str] = None
    thread_id: Optional[str] = None


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    thread_id = request.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    image_path = None

    # 处理图片逻辑
    if request.image_url:
        if len(request.image_url) > 500 or "base64" in request.image_url:
            try:
                encoded = request.image_url.split(",", 1)[1] if "," in request.image_url else request.image_url
                image_data = base64.b64decode(encoded)
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".png",
                    mode="wb",
                    dir=str(TMP_IMAGES_DIR)
                ) as tmp:
                    tmp.write(image_data)
                    image_path = tmp.name
            except Exception as e:
                print(f"图片处理失败：{e}")
        else:
            image_path = request.image_url

    input_messages = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=request.message)
    ]

    final_state = await router_app.ainvoke(
        {
            "messages": input_messages,
            "thread_id": thread_id,
            "image_url": image_path
        },
        config=config
    )
    response_text = final_state["messages"][-1].content

    return {
        "response": response_text,
        "thread_id": thread_id,
        "image_dir": f"{SERVER_URL}/images/"
    }

if __name__ == "__main__":
    import uvicorn

    print(f"Agent Server 正在启动，监听端口 {MAIN_SERVER_PORT}...")
    uvicorn.run(app, host=MAIN_SERVER_HOST, port=MAIN_SERVER_PORT)