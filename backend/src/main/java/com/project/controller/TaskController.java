package com.project.controller;

import com.project.common.Result;
import com.project.service.TaskService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/**
 * 任务提交控制器。
 *
 * 端点: POST /api/task/submit
 * 接收前端上传的图片、提示词、风格类型及各类参数（CFG scale、分辨率、控制强度等），
 * 创建任务并返回 taskId 供前端后续轮询进度。
 */
@RestController
@RequestMapping("/api/task")
public class TaskController {

    private static final Logger log = LoggerFactory.getLogger(TaskController.class);

    @Autowired
    private TaskService taskService;

    /**
     * 提交图片生成任务。
     *
     * @param image           上传图片（必填）
     * @param prompt          主体描述提示词（必填）
     * @param aPrompt         附加正向提示词
     * @param nPrompt         负向提示词
     * @param numSamples      生成张数 (1~4)
     * @param imageResolution 输入图片分辨率
     * @param ddimSteps       采样步数 (1~50)
     * @param guessMode       ControlNet 猜测模式
     * @param strength        ControlNet 控制强度
     * @param scale           CFG guidance scale（调节提示词影响力）
     * @param seed            随机种子，-1 为随机
     * @param eta             DDIM eta 随机性参数
     * @param lowThreshold    Canny 低阈值（边缘密度控制）
     * @param highThreshold   Canny 高阈值（边缘密度控制）
     * @return 包含 taskId 和初始状态的响应
     */
    @PostMapping("/submit")
    public Result<Map<String, Object>> submitTask(
            @RequestParam("image") MultipartFile image,
            @RequestParam("prompt") String prompt,
            @RequestParam(value = "aPrompt", defaultValue = "best quality, extremely detailed") String aPrompt,
            @RequestParam(value = "nPrompt", defaultValue = "longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality") String nPrompt,
            @RequestParam(value = "numSamples", defaultValue = "1") Integer numSamples,
            @RequestParam(value = "imageResolution", defaultValue = "512") Integer imageResolution,
            @RequestParam(value = "ddimSteps", defaultValue = "20") Integer ddimSteps,
            @RequestParam(value = "guessMode", defaultValue = "false") Boolean guessMode,
            @RequestParam(value = "strength", defaultValue = "1.0") Double strength,
            @RequestParam(value = "scale", defaultValue = "9.0") Double scale,
            @RequestParam(value = "seed", defaultValue = "-1") Integer seed,
            @RequestParam(value = "eta", defaultValue = "0.0") Double eta,
            @RequestParam(value = "lowThreshold", defaultValue = "100") Integer lowThreshold,
            @RequestParam(value = "highThreshold", defaultValue = "200") Integer highThreshold
    ) {
        if (image == null || image.isEmpty()) {
            return Result.error(400, "图片文件不能为空");
        }
        if (prompt == null || prompt.trim().isEmpty()) {
            return Result.error(400, "提示词 prompt 不能为空");
        }

        try {
            Long taskId = taskService.submitTask(
                    image, prompt, aPrompt, nPrompt,
                    numSamples, imageResolution, ddimSteps,
                    guessMode, strength, scale, seed, eta,
                    lowThreshold, highThreshold
            );
            Map<String, Object> data = new HashMap<>();
            data.put("taskId", taskId);
            data.put("status", "PENDING");
            log.info("任务提交成功, taskId={}", taskId);
            return Result.success(data);
        } catch (IOException e) {
            log.error("任务提交失败: {}", e.getMessage(), e);
            return Result.error("任务提交失败: " + e.getMessage());
        }
    }
}
