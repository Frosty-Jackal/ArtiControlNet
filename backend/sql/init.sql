-- ArtiControlNet 数据库初始化脚本
-- 执行前请先创建数据库: CREATE DATABASE arti_control_net DEFAULT CHARACTER SET utf8mb4;

USE arti_control_net;

-- ============================================================
-- 任务主表
-- 记录每次生成任务的参数配置与当前状态
-- ============================================================
CREATE TABLE IF NOT EXISTS task (
    id               BIGINT      NOT NULL AUTO_INCREMENT COMMENT '任务ID',
    prompt           TEXT        NOT NULL                COMMENT '主体描述提示词',
    a_prompt         TEXT                                COMMENT '附加正向提示词（质量增强）',
    n_prompt         TEXT                                COMMENT '负向提示词（避免低质量）',
    num_samples      INT         NOT NULL DEFAULT 1      COMMENT '生成张数 (1~4)',
    image_resolution INT         NOT NULL DEFAULT 512    COMMENT '输入图片调整分辨率',
    ddim_steps       INT         NOT NULL DEFAULT 20     COMMENT 'DDIM 采样步数 (1~50)',
    guess_mode       TINYINT(1)  NOT NULL DEFAULT 0      COMMENT 'ControlNet 猜测模式 (0/1)',
    strength         DOUBLE      NOT NULL DEFAULT 1.0    COMMENT 'ControlNet 控制强度',
    scale            DOUBLE      NOT NULL DEFAULT 9.0    COMMENT 'CFG guidance scale',
    seed             INT         NOT NULL DEFAULT -1     COMMENT '随机种子，-1 为随机生成',
    eta              DOUBLE      NOT NULL DEFAULT 0.0    COMMENT 'DDIM eta 随机性参数',
    low_threshold    INT         NOT NULL DEFAULT 100    COMMENT 'Canny 低阈值',
    high_threshold   INT         NOT NULL DEFAULT 200    COMMENT 'Canny 高阈值',
    status           VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '任务状态: PENDING/PROCESSING/COMPLETED/FAILED',
    error_msg        TEXT                                COMMENT '失败时的错误信息',
    created_at       DATETIME    NOT NULL                COMMENT '任务创建时间',
    updated_at       DATETIME    NOT NULL                COMMENT '最后更新时间',
    PRIMARY KEY (id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 生成任务主表';


-- ============================================================
-- 任务时间表
-- 追踪任务各阶段的时间节点
-- ============================================================
CREATE TABLE IF NOT EXISTS task_time (
    id            BIGINT   NOT NULL AUTO_INCREMENT COMMENT '记录ID',
    task_id       BIGINT   NOT NULL                COMMENT '关联任务ID',
    created_time  DATETIME                         COMMENT '任务创建时间',
    start_time    DATETIME                         COMMENT '任务开始处理时间（进入PROCESSING）',
    complete_time DATETIME                         COMMENT '任务完成时间（COMPLETED/FAILED）',
    PRIMARY KEY (id),
    INDEX idx_task_id (task_id),
    CONSTRAINT fk_task_time_task FOREIGN KEY (task_id) REFERENCES task (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务执行时间追踪表';


-- ============================================================
-- 图片存储表
-- 以 LONGBLOB 存储原始图、Canny 边缘图和生成结果图
-- ============================================================
CREATE TABLE IF NOT EXISTS picture (
    id            BIGINT      NOT NULL AUTO_INCREMENT COMMENT '图片ID',
    task_id       BIGINT      NOT NULL                COMMENT '关联任务ID',
    picture_data  LONGBLOB                            COMMENT '图片二进制数据 (PNG格式)',
    picture_type  VARCHAR(20) NOT NULL                COMMENT '图片类型: SOURCE/EDGE/RESULT',
    sort_order    INT         NOT NULL DEFAULT 0      COMMENT '同任务多张图的排序序号',
    created_at    DATETIME    NOT NULL                COMMENT '图片存储时间',
    PRIMARY KEY (id),
    INDEX idx_task_id (task_id),
    INDEX idx_task_type (task_id, picture_type),
    CONSTRAINT fk_picture_task FOREIGN KEY (task_id) REFERENCES task (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务图片存储表（BLOB）';
