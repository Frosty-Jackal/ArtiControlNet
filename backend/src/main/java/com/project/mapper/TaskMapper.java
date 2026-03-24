package com.project.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.project.entity.Task;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface TaskMapper extends BaseMapper<Task> {

    /**
     * 更新任务状态与错误信息，同时自动刷新 updated_at 字段。
     */
    @Update("UPDATE task SET status = #{status}, error_msg = #{errorMsg}, updated_at = NOW() WHERE id = #{taskId}")
    int updateStatusAndError(@Param("taskId") Long taskId,
                             @Param("status") String status,
                             @Param("errorMsg") String errorMsg);
}
