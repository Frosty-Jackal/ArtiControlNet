package com.project.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 任务进度查询响应体。
 * 当 status 为 COMPLETED 时，images 列表中包含 Base64 编码的图片字符串
 * （第一张为 Canny 边缘图，其余为生成结果图）。
 */
@Data
public class TaskProgressResponse {

    private Long taskId;

    /** 当前任务状态: PENDING / PROCESSING / COMPLETED / FAILED */
    private String status;

    /** 失败时的错误描述 */
    private String errorMsg;

    /**
     * 生成完成后的图片列表（Base64 data URI 格式）。
     * index 0: Canny 边缘图；index 1+: 生成结果图。
     */
    private List<String> images;

    /** 任务时间信息 */
    private TimeInfo timeInfo;

    @Data
    public static class TimeInfo {
        private LocalDateTime createdTime;
        private LocalDateTime startTime;
        private LocalDateTime completeTime;
    }
}
