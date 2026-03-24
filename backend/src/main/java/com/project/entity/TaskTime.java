package com.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 任务时间记录表，追踪任务创建、开始处理、完成的时间节点。
 */
@Data
@TableName("task_time")
public class TaskTime {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 关联的任务 ID */
    private Long taskId;

    /** 任务创建时间 */
    private LocalDateTime createdTime;

    /** 任务开始处理时间（进入 PROCESSING 状态） */
    private LocalDateTime startTime;

    /** 任务完成时间（COMPLETED 或 FAILED） */
    private LocalDateTime completeTime;
}
