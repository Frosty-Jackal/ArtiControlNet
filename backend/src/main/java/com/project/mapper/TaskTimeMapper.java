package com.project.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.project.entity.TaskTime;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface TaskTimeMapper extends BaseMapper<TaskTime> {

    /**
     * 记录任务开始处理的时间戳。
     */
    @Update("UPDATE task_time SET start_time = NOW() WHERE task_id = #{taskId}")
    int updateStartTime(@Param("taskId") Long taskId);

    /**
     * 记录任务完成（成功或失败）的时间戳。
     */
    @Update("UPDATE task_time SET complete_time = NOW() WHERE task_id = #{taskId}")
    int updateCompleteTime(@Param("taskId") Long taskId);
}
