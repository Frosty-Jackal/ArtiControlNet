package com.project.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.project.entity.Picture;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface PictureMapper extends BaseMapper<Picture> {

    /**
     * 查询指定任务下所有结果图（EDGE + RESULT），按 sort_order 升序排列。
     */
    @Select("SELECT * FROM picture WHERE task_id = #{taskId} AND picture_type != 'SOURCE' ORDER BY sort_order ASC")
    List<Picture> selectResultPicturesByTaskId(@Param("taskId") Long taskId);

    /**
     * 查询指定任务的原始输入图。
     */
    @Select("SELECT * FROM picture WHERE task_id = #{taskId} AND picture_type = 'SOURCE' LIMIT 1")
    Picture selectSourcePicture(@Param("taskId") Long taskId);
}
