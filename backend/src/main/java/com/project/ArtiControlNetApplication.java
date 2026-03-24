package com.project;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
@MapperScan("com.project.mapper")
public class ArtiControlNetApplication {
    public static void main(String[] args) {
        SpringApplication.run(ArtiControlNetApplication.class, args);
    }
}
