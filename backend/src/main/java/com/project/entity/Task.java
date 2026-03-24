package com.project.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 任务主表，记录每次生成任务的参数配置与当前状态。
 * status 取值: PENDING(排队中) / PROCESSING(生成中) / COMPLETED(完成) / FAILED(失败)
 */
@Data
@TableName("task")
public class Task {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 主体描述提示词 */
    private String prompt;

    /** 附加正向提示词（质量增强） */
    private String aPrompt;

    /** 负向提示词（避免低质量内容） */
    private String nPrompt;

    /** 一次生成的图片数量，范围 1~4 */
    private Integer numSamples;

    /** 输入图片调整目标分辨率 */
    private Integer imageResolution;

    /** DDIM 采样步数，范围 1~50 */
    private Integer ddimSteps;

    /** ControlNet 猜测模式（控制约束逐层衰减） */
    private Boolean guessMode;

    /** ControlNet 控制强度，值越大越贴近边缘 */
    private Double strength;

    /** CFG guidance scale，控制 prompt 影响程度 */
    private Double scale;

    /** 随机种子，-1 表示随机生成 */
    private Integer seed;

    /** DDIM 随机性参数，0 为完全确定性 */
    private Double eta;

    /** Canny 低阈值 */
    private Integer lowThreshold;

    /** Canny 高阈值 */
    private Integer highThreshold;

    /** 任务状态: PENDING / PROCESSING / COMPLETED / FAILED */
    private String status;

    /** 失败时记录错误信息 */
    private String errorMsg;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
