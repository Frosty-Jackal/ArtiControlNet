package com.project.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 图片存储表，以 BLOB 格式保存每次任务的源图与生成结果图。
 * pictureType 取值: SOURCE(原始输入图) / EDGE(Canny 边缘图) / RESULT(生成结果图)
 */
@Data
@TableName("picture")
public class Picture {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 关联的任务 ID */
    private Long taskId;

    /** 图片二进制数据（PNG 格式，LONGBLOB 存储） */
    private byte[] pictureData;

    /** 图片类型: SOURCE / EDGE / RESULT */
    private String pictureType;

    /** 同一任务中多张结果图的排列顺序，从 0 开始 */
    private Integer sortOrder;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
