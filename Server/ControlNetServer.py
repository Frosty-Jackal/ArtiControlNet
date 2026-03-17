import os
import traceback

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


from Server.StableDiffusionEngine import StableDiffusionEngine
from Server.schemas import ControlNetRequest
from Server.tools.canny import CannyTool
from Server.utils import ImageUtils
from Server.tools.scribble import ScribbleTool

class ControlNetServer:
    def __init__(self):
        self.app = FastAPI(title="ControlNet Agent API")
        self.setup_middleware()
        self.setup_routes()
        self.setup_static()

        # 初始化引擎和工具
        # 注意：这里在启动时就会加载模型，可能会花一点时间
        self.engine = StableDiffusionEngine()
        self.canny_tool = CannyTool(self.engine)
        self.scribble_tool = ScribbleTool(self.engine)

    def setup_middleware(self):
        # 解决跨域问题，允许前端访问
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def setup_static(self):
        ImageUtils.ensure_directories()
        self.app.mount("/static", StaticFiles(directory="static"), name="static")

    def setup_routes(self):
        @self.app.get("/")
        async def read_index():
            if os.path.exists("static/index.html"):
                return FileResponse("static/index.html")
            return {"message": "Server is running"}

        @self.app.post("/api/controlnet/generate_canny")
        async def generate_canny(request: ControlNetRequest):
            try:
                # 路由函数只负责转发给 Tool 类
                return await self.canny_tool.inference(request)
            except Exception as ex:
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=str(ex))

            # 新增 Scribble 路由
        @self.app.post("/api/controlnet/generate_scribble")
        async def generate_scribble_endpoint(request: ControlNetRequest):
            try:
                return await self.scribble_tool.inference(request)
            except Exception as ex:
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=str(ex))


    def run(self, host="0.0.0.0", port=6006):
        uvicorn.run(self.app, host=host, port=port)

if __name__ == "__main__":
    ControlNetServer().run()