package com.project.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * Python FastAPI 服务 /api/controlnet/generate_canny 的响应结构。
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class PythonResponse {

    /** 响应状态，"success" 表示成功 */
    private String status;

    /**
     * Base64 编码的图片列表（data:image/png;base64,...）。
     * index 0: Canny 边缘图；index 1+: 生成结果图。
     */
    private List<String> images;

    /** 附加信息，包含实际使用的 seed、尺寸等 */
    private Map<String, Object> info;
}
