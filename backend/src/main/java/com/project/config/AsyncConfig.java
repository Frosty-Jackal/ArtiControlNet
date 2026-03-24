package com.project.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * 异步任务线程池配置。
 *
 * AI 推理任务单次耗时较长（数十秒），使用独立线程池隔离，
 * 避免占用 Spring Web 默认线程池导致接口响应延迟。
 */
@Configuration
public class AsyncConfig {

    @Bean("taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        // 核心线程数：并行处理的最大任务数，根据 GPU 数量调整（单 GPU 建议设为 1~2）
        executor.setCorePoolSize(2);
        // 最大线程数
        executor.setMaxPoolSize(4);
        // 任务队列容量（超出时触发拒绝策略）
        executor.setQueueCapacity(50);
        // 空闲线程存活时间（秒）
        executor.setKeepAliveSeconds(60);
        executor.setThreadNamePrefix("task-exec-");
        // 拒绝策略：由调用方线程执行（防止任务丢失）
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        // 应用关闭时等待任务完成
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(300);
        executor.initialize();
        return executor;
    }
}
