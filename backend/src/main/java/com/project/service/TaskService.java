package com.project.service;

import com.project.dto.TaskProgressResponse;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

/**
 * 任务业务服务接口，定义任务的提交与进度查询能力。
 */
public interface TaskService {

    /**
     * 提交生成任务：持久化任务参数和源图，异步触发 Python 推理。
     *
     * @param image           前端上传的原始图片
     * @param prompt          主体描述提示词
     * @param aPrompt         附加正向提示词
     * @param nPrompt         负向提示词
     * @param numSamples      生成数量 (1~4)
     * @param imageResolution 图片分辨率
     * @param ddimSteps       采样步数 (1~50)
     * @param guessMode       ControlNet 猜测模式
     * @param strength        控制强度
     * @param scale           CFG scale
     * @param seed            随机种子，-1 表示随机
     * @param eta             DDIM eta
     * @param lowThreshold    Canny 低阈值
     * @param highThreshold   Canny 高阈值
     * @return 新建任务的 ID
     */
    Long submitTask(MultipartFile image,
                    String prompt,
                    String aPrompt,
                    String nPrompt,
                    Integer numSamples,
                    Integer imageResolution,
                    Integer ddimSteps,
                    Boolean guessMode,
                    Double strength,
                    Double scale,
                    Integer seed,
                    Double eta,
                    Integer lowThreshold,
                    Integer highThreshold) throws IOException;

    /**
     * 查询任务当前进度，任务完成后返回 Base64 图片列表。
     *
     * @param taskId 任务 ID
     * @return 进度响应体
     */
    TaskProgressResponse getProgress(Long taskId);
}
