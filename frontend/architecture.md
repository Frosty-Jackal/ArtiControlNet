src/
├── api/
│   └── taskApi.js
├── assets/
│   └── styles/
├── components/
│   ├── DrawConfigPanel.vue
│   ├── AdjustToolbar.vue
│   ├── OperationControls.vue
│   └── ProgressIndicator.vue
├── views/
│   └── DrawingWorkspace.vue
├── router/
├── store/
└── App.vue


核心文件与功能映射说明：

api/taskApi.js: 统一封装与Java后端的通信接口，包括提交生成请求和查询任务最新状态 。


components/DrawConfigPanel.vue: 实现绘图任务的导入选项，包含选择示例图、输入提示词、选择预置提示词及选择风格 。


components/AdjustToolbar.vue: 封装调整任务所需的深度控制、色彩检测、边缘检测、镜头效果和色彩校正工具栏 。


components/OperationControls.vue: 承载操作任务的功能，包括变化强弱的重新生成、二次生成以及尺寸调节 。


components/ProgressIndicator.vue: 负责展示查看生成进度的界面，实时反馈任务状态（排队中/生成中/完成/失败） 。

views/DrawingWorkspace.vue: 主工作区视图，将上述组件进行整合与布局。