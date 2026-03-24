src/main/java/com/project/
├── controller/
│   ├── TaskController.java
│   └── ProgressController.java
├── service/
│   ├── TaskService.java
│   └── impl/TaskServiceImpl.java
├── entity/
│   ├── Task.java
│   ├── TaskTime.java
│   └── Picture.java
├── mapper/
│   ├── TaskMapper.java
│   ├── TaskTimeMapper.java
│   └── PictureMapper.java
├── config/
└── utils/
    └── HttpUtils.java


核心文件与功能映射说明：

controller/TaskController.java: 暴露API端点，接收前端提交的图片、提示词、风格类型 ；同时接收更改后的“CFG”参数和尺寸参数等操作指令 。

controller/ProgressController.java: 提供查询接口，向前端返回当前任务状态数据 。

service/impl/TaskServiceImpl.java: 处理核心业务逻辑，包括创建任务和图片记录，并负责用POST方法将任务内容提交到服务器网址 。

entity/Task.java: 实体类，对应数据库，用于写入任务信息到 task 表 。

entity/TaskTime.java: 实体类，用于更新任务完成时间到 task_time 表 。

entity/Picture.java: 实体类，用于储存每次任务图片，对应数据库中以BLOB数据类型存储的 picture 表 。

utils/HttpUtils.java: 封装HTTP请求工具，专门用于向Python服务端发送POST请求并接收输出的生成图片 。


后端代码结构总览：
backend/
├── pom.xml                          # Maven 依赖（Spring Boot 3.2 / MyBatis-Plus / OkHttp / MySQL）
├── sql/
│   └── init.sql                     # 三张表的建库建表 SQL
└── src/main/java/com/project/
    ├── ArtiControlNetApplication.java  # 启动类（开启 @Async + @MapperScan）
    ├── common/
    │   └── Result.java               # 统一响应包装 { code, message, data }
    ├── config/
    │   ├── AsyncConfig.java          # 推理专用线程池（核心2/最大4线程，队列50）
    │   ├── CorsConfig.java           # CORS 跨域配置（放通 /api/** 所有来源）
    │   └── MybatisPlusConfig.java    # 自动填充 createdAt / updatedAt
    ├── controller/
    │   ├── TaskController.java       # POST /api/task/submit（接收图片+参数，返回 taskId）
    │   └── ProgressController.java   # GET /api/task/progress/{taskId}（返回状态+图片）
    ├── dto/
    │   ├── PythonResponse.java       # Python 服务响应结构（status + images + info）
    │   └── TaskProgressResponse.java # 进度查询响应（status + images + timeInfo）
    ├── entity/
    │   ├── Task.java                 # task 表（参数 + 状态 + 时间戳）
    │   ├── TaskTime.java             # task_time 表（创建/开始/完成时间）
    │   └── Picture.java             # picture 表（LONGBLOB 图片数据）
    ├── mapper/
    │   ├── TaskMapper.java           # 含 updateStatusAndError 自定义更新
    │   ├── TaskTimeMapper.java       # 含 updateStartTime / updateCompleteTime
    │   └── PictureMapper.java        # 含按 taskId 查询结果图/源图
    ├── service/
    │   ├── TaskService.java          # 接口定义
    │   └── impl/TaskServiceImpl.java # 核心实现（同步写库 + @Async 推理）
    └── utils/
        └── HttpUtils.java            # OkHttp 封装，发送 multipart POST 到 Python

核心工作流：
前端 POST /api/task/submit
    → TaskController
    → TaskServiceImpl.submitTask()
        ① 写 task 表（状态: PENDING）
        ② 写 picture 表（SOURCE 原图）
        ③ 写 task_time 表（createdTime）
        ④ 异步触发 executeTask()
    ← 立即返回 { taskId, status: "PENDING" }

异步线程（taskExecutor）
    → 更新 status=PROCESSING，写 startTime
    → HttpUtils.callControlNetGenerate() → Python :8000
    ← 接收 Base64 图片列表（[边缘图, 结果图×N]）
    → 解码为 byte[] 写入 picture 表（EDGE / RESULT）
    → 更新 status=COMPLETED，写 completeTime
    （失败时 status=FAILED + errorMsg）

前端轮询 GET /api/task/progress/{taskId}
    → ProgressController → TaskServiceImpl.getProgress()
    ← { status, timeInfo, images: ["data:image/png;base64,..."] }