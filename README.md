# CoachLoop-FS · V4教师工作台

已准备主环境的Mac：双击`scripts/start_prelesson_console.command`，服务启动后自动尝试打开本机教师首页。
选择L01–L08即可载入45分钟中文草稿；空资料库可阅读说明后初始化待审核候选。普通使用无需理解JSON。

[教师使用与首次启动说明](docs/v4-teacher/README.md) · [浏览器验收与截图](docs/v4-teacher/acceptance-report.md)

原V1.1多主题及研发参数保留在本机`/advanced`高级模式。知识审核、视频本地处理、私有会话与专业边界不变。
首次主环境仍需维护者准备；本轮不是Mac原生安装包，不冒充已完成真实教师或花滑视频验收。

---

# 项目结构说明

# 本地运行
## 运行流程
bash scripts/local_run.sh -m flow

## 运行节点
bash scripts/local_run.sh -m node -n node_name

# 启动HTTP服务
bash scripts/http_run.sh -m http -p 5000

