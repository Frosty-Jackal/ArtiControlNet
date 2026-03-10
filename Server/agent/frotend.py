import gradio as gr
import requests
import base64
import os

# 你的 Agent 后端地址
AGENT_API_URL = "http://localhost:8000/api/chat"


# 辅助函数：把文件路径转 Base64
def file_to_base64(file_path):
    with open(file_path, "rb") as f:
        encoded_string = base64.b64encode(f.read()).decode('utf-8')
    return f"data:image/jpeg;base64,{encoded_string}"


def chat_function(message, history, current_file_path, saved_base64_state):
    """
    message: 文字
    history: 历史
    current_file_path: 【关键】这是从 State 里取出的当前文件路径，而不是按钮的值
    saved_base64_state: 之前的 Base64 记忆
    """
    if history is None:
        history = []

    # 1. 决定使用哪张图片
    image_b64_to_send = None
    display_path = None

    # A. 优先查看当前是否有新文件 (来自 State)
    if current_file_path:
        print(f"发现新图片路径: {current_file_path}")
        try:
            image_b64_to_send = file_to_base64(current_file_path)
            display_path = current_file_path
        except Exception as e:
            print(f"读取文件失败: {e}")

    # B. 如果没有新文件，检查有没有历史记忆
    elif saved_base64_state:
        print("♻️ 使用历史图片记忆...")
        image_b64_to_send = saved_base64_state

    # 2. 构造 Payload
    payload = {
        "message": message,
        "thread_id": None,
        "image_url": None
    }

    user_content = message

    if image_b64_to_send:
        payload["image_url"] = image_b64_to_send
        payload["message"] = f"{message} (包含图片数据)"

        # 界面显示
        if display_path:
            user_content = f"{message}\n\n![ref]({display_path})"
        elif saved_base64_state:
            user_content = f"{message} [已关联参考图]"

    # 3. 发送请求
    try:
        # print(f"正在发送... Image Length: {len(str(payload['image_url']))}")
        response = requests.post(AGENT_API_URL, json=payload, timeout=480)
        response.raise_for_status()
        data = response.json()
        bot_response = data["response"]
    except Exception as e:
        bot_response = f"错误: {str(e)}"

    # 4. 更新历史
    history.append({"role": "user", "content": user_content})
    history.append({"role": "assistant", "content": bot_response})

    # 返回值说明:
    # 1. history: 更新聊天框
    # 2. "": 清空输入框
    # 3. image_b64_to_send: 更新【长期记忆】(Saved State)
    # 4. None: 清空【当前文件路径】(File State)，防止下次重复发同一张图
    # 5. "未选择文件": 重置上传提示文字
    return history, "", image_b64_to_send, None, "未选择文件"


# --- 界面构建 ---

with gr.Blocks(title="AI 绘图助手 (修复版)") as demo:
    gr.Markdown("# ControlNet AI 绘图助手")

    with gr.Row():
        with gr.Column(scale=4):
            chatbot = gr.Chatbot(height=600, label="对话历史")

    with gr.Row():
        with gr.Column(scale=4):
            msg = gr.Textbox(placeholder="输入指令...", show_label=False, container=False)
        with gr.Column(scale=1):
            upload_btn = gr.UploadButton("上传图片", file_types=["image"])
            upload_status = gr.Markdown("未选择文件")

    # 【核心修复】引入两个状态变量
    saved_memory = gr.State(None)  # 长期记忆 (存 Base64)
    file_buffer = gr.State(None)  # 短期缓存 (存刚刚上传的文件路径)


    # 1. 上传事件：把文件路径存入 file_buffer (State)
    # 这样即使按钮清空了，State 里的路径还在
    def on_upload(file):
        if file:
            return file.name, f"已就绪: {os.path.basename(file.name)}"
        return None, "未选择文件"


    upload_btn.upload(
        fn=on_upload,
        inputs=upload_btn,
        outputs=[file_buffer, upload_status]  # 更新 buffer 和 提示字
    )

    # 2. 发送事件：读取 file_buffer 而不是 upload_btn
    msg.submit(
        fn=chat_function,
        inputs=[msg, chatbot, file_buffer, saved_memory],  # 读取 State
        outputs=[chatbot, msg, saved_memory, file_buffer, upload_status]
    )

if __name__ == "__main__":
    print("前端服务启动中...")
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)