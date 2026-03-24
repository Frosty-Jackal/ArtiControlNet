package com.project.utils;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.project.dto.PythonResponse;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

/**
 * HTTP 请求工具类，专门用于向 Python FastAPI 服务端发送 multipart/form-data 请求
 * 并接收生成的图片结果。
 *
 * Python 服务端点: POST /api/controlnet/generate_canny
 * 默认地址: http://localhost:8000
 */
public class HttpUtils {

    private static final Logger log = LoggerFactory.getLogger(HttpUtils.class);

    private static final MediaType MEDIA_TYPE_PNG = MediaType.parse("image/png");
    private static final MediaType MEDIA_TYPE_JPEG = MediaType.parse("image/jpeg");
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /** OkHttp 客户端单例，设置较长超时以应对 AI 推理耗时 */
    private static final OkHttpClient HTTP_CLIENT = new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .readTimeout(300, TimeUnit.SECONDS)
            .build();

    private HttpUtils() {}

    /**
     * 调用 Python ControlNet 服务，发送图片及参数，返回结构化响应。
     *
     * @param pythonServerUrl Python 服务基础地址（如 http://localhost:8000）
     * @param imageBytes      原始图片字节数组
     * @param imageFilename   上传文件名（用于 MIME 类型判断）
     * @param prompt          主体描述提示词
     * @param aPrompt         附加正向提示词
     * @param nPrompt         负向提示词
     * @param numSamples      生成数量
     * @param imageResolution 图片目标分辨率
     * @param ddimSteps       DDIM 采样步数
     * @param guessMode       是否启用猜测模式
     * @param strength        控制强度
     * @param scale           CFG guidance scale
     * @param seed            随机种子
     * @param eta             DDIM eta 参数
     * @param lowThreshold    Canny 低阈值
     * @param highThreshold   Canny 高阈值
     * @return PythonResponse 包含 Base64 编码的图片列表
     * @throws IOException 网络或服务端异常
     */
    public static PythonResponse callControlNetGenerate(
            String pythonServerUrl,
            byte[] imageBytes,
            String imageFilename,
            String prompt,
            String aPrompt,
            String nPrompt,
            int numSamples,
            int imageResolution,
            int ddimSteps,
            boolean guessMode,
            double strength,
            double scale,
            int seed,
            double eta,
            int lowThreshold,
            int highThreshold
    ) throws IOException {
        String url = pythonServerUrl.replaceAll("/$", "") + "/api/controlnet/generate_canny";
        log.info("向 Python 服务发送请求: {}, prompt={}", url, prompt);

        MediaType imageMediaType = resolveImageMediaType(imageFilename);

        MultipartBody requestBody = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("image", imageFilename,
                        RequestBody.create(imageBytes, imageMediaType))
                .addFormDataPart("prompt", prompt)
                .addFormDataPart("a_prompt", aPrompt)
                .addFormDataPart("n_prompt", nPrompt)
                .addFormDataPart("num_samples", String.valueOf(numSamples))
                .addFormDataPart("image_resolution", String.valueOf(imageResolution))
                .addFormDataPart("ddim_steps", String.valueOf(ddimSteps))
                .addFormDataPart("guess_mode", String.valueOf(guessMode))
                .addFormDataPart("strength", String.valueOf(strength))
                .addFormDataPart("scale", String.valueOf(scale))
                .addFormDataPart("seed", String.valueOf(seed))
                .addFormDataPart("eta", String.valueOf(eta))
                .addFormDataPart("low_threshold", String.valueOf(lowThreshold))
                .addFormDataPart("high_threshold", String.valueOf(highThreshold))
                .build();

        Request request = new Request.Builder()
                .url(url)
                .post(requestBody)
                .build();

        try (Response response = HTTP_CLIENT.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                String errorBody = response.body() != null ? response.body().string() : "无响应体";
                log.error("Python 服务返回错误 HTTP {}: {}", response.code(), errorBody);
                throw new IOException("Python 服务返回异常状态码 " + response.code() + ": " + errorBody);
            }
            String responseBody = response.body().string();
            log.info("Python 服务响应成功，响应体长度: {} 字符", responseBody.length());
            return OBJECT_MAPPER.readValue(responseBody, PythonResponse.class);
        }
    }

    /**
     * 根据文件名后缀判断图片 MIME 类型，未知格式默认为 PNG。
     */
    private static MediaType resolveImageMediaType(String filename) {
        if (filename == null) return MEDIA_TYPE_PNG;
        String lower = filename.toLowerCase();
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
            return MEDIA_TYPE_JPEG;
        }
        return MEDIA_TYPE_PNG;
    }
}
