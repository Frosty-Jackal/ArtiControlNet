package com.project.controller;

import com.project.common.Result;
import com.project.dto.TaskProgressResponse;
import com.project.service.TaskService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

/**
 * 任务进度查询控制器。
 *
 * 端点: GET /api/task/progress/{taskId}
 * 向前端返回当前任务状态数据（排队中/生成中/完成/失败）。
 * 任务完成时，响应体中包含 Base64 格式的图片列表（边缘图 + 生成结果图）。
 *
 * 前端建议采用轮询策略（如每 2 秒请求一次），直至状态变为 COMPLETED 或 FAILED。
 */
@RestController
@RequestMapping("/api/task")
public class ProgressController {

    @Autowired
    private TaskService taskService;

    /**
     * 查询指定任务的当前进度与结果。
     *
     * @param taskId 任务 ID（由 /api/task/submit 接口返回）
     * @return 进度响应，包含 status、timeInfo，完成时附带 images 列表
     */
    @GetMapping("/progress/{taskId}")
    public Result<TaskProgressResponse> getProgress(@PathVariable Long taskId) {
        TaskProgressResponse progress = taskService.getProgress(taskId);
        return Result.success(progress);
    }
}
