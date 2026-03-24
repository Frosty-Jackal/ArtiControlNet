package com.project.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.project.dto.PythonResponse;
import com.project.dto.TaskProgressResponse;
import com.project.entity.Picture;
import com.project.entity.Task;
import com.project.entity.TaskTime;
import com.project.mapper.PictureMapper;
import com.project.mapper.TaskMapper;
import com.project.mapper.TaskTimeMapper;
import com.project.service.TaskService;
import com.project.utils.HttpUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

/**
 * 任务业务实现类。
 *
 * 核心流程：
 * 1. submitTask() 将任务参数和源图写入数据库（状态: PENDING），立即返回 taskId。
 * 2. executeTask() 在独立线程池中异步运行，负责调用 Python 推理服务并持久化结果。
 * 3. getProgress() 查询数据库中的任务状态，完成后附带 Base64 图片列表返回。
 */
@Service
public class TaskServiceImpl implements TaskService {

    private static final Logger log = LoggerFactory.getLogger(TaskServiceImpl.class);

    private static final String STATUS_PENDING = "PENDING";
    private static final String STATUS_PROCESSING = "PROCESSING";
    private static final String STATUS_COMPLETED = "COMPLETED";
    private static final String STATUS_FAILED = "FAILED";

    private static final String PICTURE_TYPE_SOURCE = "SOURCE";
    private static final String PICTURE_TYPE_EDGE = "EDGE";
    private static final String PICTURE_TYPE_RESULT = "RESULT";

    @Autowired
    private TaskMapper taskMapper;

    @Autowired
    private TaskTimeMapper taskTimeMapper;

    @Autowired
    private PictureMapper pictureMapper;

    @Value("${python.server.url:http://localhost:8000}")
    private String pythonServerUrl;

    // -------------------------------------------------------------------------
    // 公开接口实现
    // -------------------------------------------------------------------------

    @Override
    public Long submitTask(MultipartFile image,
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
                           Integer highThreshold) throws IOException {

        // 1. 构建并保存任务记录
        Task task = buildTask(prompt, aPrompt, nPrompt, numSamples, imageResolution,
                ddimSteps, guessMode, strength, scale, seed, eta, lowThreshold, highThreshold);
        taskMapper.insert(task);
        Long taskId = task.getId();
        log.info("任务创建成功, taskId={}, prompt={}", taskId, prompt);

        // 2. 保存原始输入图到 picture 表
        byte[] imageBytes = image.getBytes();
        savePicture(taskId, imageBytes, PICTURE_TYPE_SOURCE, 0);

        // 3. 创建时间记录，写入 created_time
        TaskTime taskTime = new TaskTime();
        taskTime.setTaskId(taskId);
        taskTime.setCreatedTime(LocalDateTime.now());
        taskTimeMapper.insert(taskTime);

        // 4. 异步触发推理（立即返回 taskId，不阻塞前端）
        executeTask(taskId, imageBytes, image.getOriginalFilename(), task);

        return taskId;
    }

    @Override
    public TaskProgressResponse getProgress(Long taskId) {
        Task task = taskMapper.selectById(taskId);
        if (task == null) {
            TaskProgressResponse notFound = new TaskProgressResponse();
            notFound.setTaskId(taskId);
            notFound.setStatus("NOT_FOUND");
            notFound.setErrorMsg("任务不存在");
            return notFound;
        }

        TaskProgressResponse response = new TaskProgressResponse();
        response.setTaskId(taskId);
        response.setStatus(task.getStatus());
        response.setErrorMsg(task.getErrorMsg());

        // 查询时间信息
        TaskTime taskTime = taskTimeMapper.selectOne(
                new LambdaQueryWrapper<TaskTime>().eq(TaskTime::getTaskId, taskId));
        if (taskTime != null) {
            TaskProgressResponse.TimeInfo timeInfo = new TaskProgressResponse.TimeInfo();
            timeInfo.setCreatedTime(taskTime.getCreatedTime());
            timeInfo.setStartTime(taskTime.getStartTime());
            timeInfo.setCompleteTime(taskTime.getCompleteTime());
            response.setTimeInfo(timeInfo);
        }

        // 任务完成后，从数据库取出图片并转为 Base64
        if (STATUS_COMPLETED.equals(task.getStatus())) {
            List<Picture> pictures = pictureMapper.selectResultPicturesByTaskId(taskId);
            List<String> base64Images = new ArrayList<>();
            for (Picture pic : pictures) {
                String base64 = "data:image/png;base64," +
                        Base64.getEncoder().encodeToString(pic.getPictureData());
                base64Images.add(base64);
            }
            response.setImages(base64Images);
        }

        return response;
    }

    // -------------------------------------------------------------------------
    // 异步推理执行
    // -------------------------------------------------------------------------

    /**
     * 在独立线程池中执行推理，避免阻塞 HTTP 请求线程。
     * 该方法由 Spring @Async 代理调用，必须为 public 方法且通过 Spring Bean 调用生效。
     */
    @Async("taskExecutor")
    public void executeTask(Long taskId, byte[] imageBytes, String filename, Task task) {
        log.info("开始异步推理, taskId={}", taskId);

        // 更新状态为 PROCESSING，记录开始时间
        taskMapper.updateStatusAndError(taskId, STATUS_PROCESSING, null);
        taskTimeMapper.updateStartTime(taskId);

        try {
            PythonResponse pythonResponse = HttpUtils.callControlNetGenerate(
                    pythonServerUrl,
                    imageBytes,
                    filename != null ? filename : "input.png",
                    task.getPrompt(),
                    task.getAPrompt(),
                    task.getNPrompt(),
                    task.getNumSamples(),
                    task.getImageResolution(),
                    task.getDdimSteps(),
                    task.getGuessMode(),
                    task.getStrength(),
                    task.getScale(),
                    task.getSeed(),
                    task.getEta(),
                    task.getLowThreshold(),
                    task.getHighThreshold()
            );

            if (!"success".equals(pythonResponse.getStatus()) || pythonResponse.getImages() == null) {
                throw new RuntimeException("Python 服务返回非成功状态: " + pythonResponse.getStatus());
            }

            // 保存推理结果图（index 0 为边缘图，其余为生成图）
            List<String> images = pythonResponse.getImages();
            for (int i = 0; i < images.size(); i++) {
                String base64DataUri = images.get(i);
                byte[] imgBytes = decodeBase64DataUri(base64DataUri);
                String picType = (i == 0) ? PICTURE_TYPE_EDGE : PICTURE_TYPE_RESULT;
                savePicture(taskId, imgBytes, picType, i);
            }

            // 更新状态为 COMPLETED，记录完成时间
            taskMapper.updateStatusAndError(taskId, STATUS_COMPLETED, null);
            taskTimeMapper.updateCompleteTime(taskId);
            log.info("任务推理完成, taskId={}, 共 {} 张图片", taskId, images.size());

        } catch (Exception e) {
            log.error("任务推理失败, taskId={}, 原因: {}", taskId, e.getMessage(), e);
            String errorMsg = e.getMessage() != null ? e.getMessage() : "未知错误";
            // 限制错误信息长度，避免超出数据库字段
            if (errorMsg.length() > 500) {
                errorMsg = errorMsg.substring(0, 500);
            }
            taskMapper.updateStatusAndError(taskId, STATUS_FAILED, errorMsg);
            taskTimeMapper.updateCompleteTime(taskId);
        }
    }

    // -------------------------------------------------------------------------
    // 私有辅助方法
    // -------------------------------------------------------------------------

    private Task buildTask(String prompt, String aPrompt, String nPrompt,
                            Integer numSamples, Integer imageResolution, Integer ddimSteps,
                            Boolean guessMode, Double strength, Double scale,
                            Integer seed, Double eta, Integer lowThreshold, Integer highThreshold) {
        Task task = new Task();
        task.setPrompt(prompt);
        task.setAPrompt(aPrompt);
        task.setNPrompt(nPrompt);
        task.setNumSamples(numSamples);
        task.setImageResolution(imageResolution);
        task.setDdimSteps(ddimSteps);
        task.setGuessMode(guessMode);
        task.setStrength(strength);
        task.setScale(scale);
        task.setSeed(seed);
        task.setEta(eta);
        task.setLowThreshold(lowThreshold);
        task.setHighThreshold(highThreshold);
        task.setStatus(STATUS_PENDING);
        task.setCreatedAt(LocalDateTime.now());
        task.setUpdatedAt(LocalDateTime.now());
        return task;
    }

    private void savePicture(Long taskId, byte[] data, String type, int sortOrder) {
        Picture picture = new Picture();
        picture.setTaskId(taskId);
        picture.setPictureData(data);
        picture.setPictureType(type);
        picture.setSortOrder(sortOrder);
        picture.setCreatedAt(LocalDateTime.now());
        pictureMapper.insert(picture);
    }

    /**
     * 解码 Base64 data URI（格式：data:image/png;base64,<base64data>）为字节数组。
     * 若非 data URI 格式，则直接尝试解码整个字符串。
     */
    private byte[] decodeBase64DataUri(String dataUri) {
        if (dataUri == null || dataUri.isEmpty()) {
            throw new IllegalArgumentException("Base64 数据为空");
        }
        String base64Data = dataUri;
        int commaIndex = dataUri.indexOf(',');
        if (commaIndex >= 0) {
            base64Data = dataUri.substring(commaIndex + 1);
        }
        return Base64.getDecoder().decode(base64Data);
    }
}
