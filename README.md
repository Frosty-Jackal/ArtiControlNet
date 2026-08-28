# ArtiControlNet 运行说明书

多智能体 AIGC 对话工作台：用自然语言（可带参考图）提出需求，主 Agent 分发，子 Agent 通过**云端模型 API** 完成「文生图 / 线稿生图 / 图像问答」。
无本地推理、无数据库，仅前端 + 后端两层。详细设计见 [Spec.md](./Spec.md)。

> **网站由后端托管，日常使用只需启动后端；前端只在改代码时才需要碰。**

| 层 | 选型 |
|---|---|
| 前端 | Vue 3 + Vite + Pinia + Axios + marked/DOMPurify（Markdown 渲染） |
| 后端 | Python 3.10+ · FastAPI · Uvicorn · LangGraph |
| 模型 | DeepSeek（路由 + 视觉 QA）· TokenHub `hy-image-v3`（文生图 + 线稿生图） |

> 每条命令给出 **Git Bash** 与 **PowerShell** 两种写法，按你实际用的终端选一种。
> 所有 API 密钥只放在 `Server/.env`（已 gitignore），切勿提交或外发。

---

## 一、首次安装（每台机器只装一次）

```bash
# 后端依赖 + 密钥模板
cd Server
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env              # Git Bash：复制模板
Copy-Item .env.example .env       # PowerShell：复制模板（选一行）
# 复制后填入 DEEPSEEK_API_KEY、TOKENHUB_API_KEY

# 前端依赖
cd ../frontend
npm install
```

## 二、启动网站（日常就这一条命令）

```bash
cd Server
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动后打开 **http://localhost:8000** 就是完整的工作台——前端页面和后端接口都由这一个进程提供，**不需要另外启动前端**。

## 三、让别人访问：公开链接（cloudflared 隧道，无需服务器/域名）

1. 确保后端已在 :8000 运行（见第二节）。
2. 首次安装 cloudflared：

   ```bash
   winget install --id Cloudflare.cloudflared
   ```

3. 新开一个终端，启动隧道：

   ```bash
   # Git Bash
   "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000

   # PowerShell（带空格的路径前面必须加 &）
   & "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000
   ```

4. 输出里形如 `https://xxx.trycloudflare.com` 的那一行就是公开链接，发给别人即可。

> 链接是**临时**的：每次重启隧道会变化；你的电脑需保持开机、两个终端都别关。
> 本机受 Clash/Mihomo 等代理影响，自己浏览器打开可能不稳，建议用手机流量测试或直接让访客访问。

需要**永久**域名/正式部署（Render、云服务器）时，另行配置，见 [Spec.md](./Spec.md)。

## 四、只有改前端代码时才需要碰（平时请跳过）

```bash
# 场景 A：改了前端代码，要让改动生效
#   → 重新构建，产物交给后端托管，然后重启后端（第二节的命令）

# Git Bash
cd frontend && npm run build && rm -rf ../Server/static/* && cp -r dist/* ../Server/static/

# PowerShell（5.1 不支持 &&，逐行执行）
cd frontend
npm run build
Remove-Item -Recurse -Force ..\Server\static\*
Copy-Item -Recurse dist\* ..\Server\static\

# 场景 B：开发调试前端（:5173，改代码热更新，自动代理 /api 到 :8000）
#   → 此时需要两个进程：一个跑后端，一个跑 npm run dev，打开 http://localhost:5173

# Git Bash
cd frontend && npm run dev

# PowerShell
cd frontend
npm run dev
```

## 五、结束程序

前台运行的窗口按 **Ctrl+C** 即可停止；**直接关掉窗口也可以**——关闭控制台窗口会终止其中运行的进程。

若进程残留、端口被占（如重启后端时报 8000 被占用）：

```bash
# Git Bash
netstat -ano | grep :8000       # 记下最后一行的 PID（第 5 列）
taskkill //F //PID <PID>        # Git Bash 的双斜杠是转义

# PowerShell
netstat -ano | findstr :8000    # 记下最后一行的 PID
taskkill /F /PID <PID>
```

## 六、注意事项

- 图片临时存放于 `Server/storage/`（TTL 1h，服务启动时清空）；多轮看图上下文存在后端内存中，重启即失——这是"无数据库"设计的固有行为。
- `API's Usage/`、`Server/.env`、`Server/storage/` 均已 gitignore，不要手动加入提交。

---

**致谢**：前端开发 王哲颢 · 前端 UI 设计 胡可欣 · 后端（AI）何贤哲 · 项目宣传册 章露瑶
