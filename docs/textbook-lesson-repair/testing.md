# 回归与浏览器验收

执行日期：2026-11-03；基线main `a8a03a7`，独立分支`fix/evidence-backed-lesson-content`。

## 真实命令与结果

```bash
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
```

1016 passed, 193 skipped, 1 warning，72.22秒。193项为191项需要显式隔离PostgreSQL连接的测试，及2项需要授权真实视频的测试；未连接生产库，未将合成关键点当作真实视频验收。警告为既有Coze依赖Pydantic配置弃用提醒。

内容边界和前端提示收尾后，重新运行相关测试：

```bash
PYTHONPATH=src .venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_textbook_lesson_content.py tests/test_teacher_v4.py
```

30 passed, 1 warning。新增14个测试实例覆盖：

- 初始化23条／27版本／50声明与L05事实关联，SQLite重启后组装相同，完整备份不变。
- 八课次45分钟9/29/7、专项实操暂缓、正式依据和技术指导为空。
- 非覆盖课次不串入前压步内容；空库不引用本机不存在的知识。
- 同ID但材料摘要不同、缺原页声明、新知识版本、拒绝状态均不匹配旧摘要。
- 版本变化后保留历史、撤下当前摘要、旧教案打印409。
- 原编辑、JSON导出、脚本拒绝、文本转义和普通编辑无法设审核通过。

```bash
.venv/bin/python -B scripts/verify_teacher_v4_browser.py \
  --textbook-check --output-dir /workspace/coachloop-evidence-release
```

真实Chromium通过。临时SQLite从空库初始化；界面实际切换八课次，L05显示图29、PDF93练习与李乡状PDF39；编辑目标并保存v2，打开HTML打印窗口并调用浏览器生成真实PDF；导出原结构JSON；合成候选事件、教师反馈、本地确认与证据变化失效流程通过；资源不足暂缓、模型缺失提示与高级入口保留。

额外在临时测试库追加明确标记SYNTHETIC的K012 v3，确认旧打印请求409、界面显示历史草稿失效。此追加仅发生在临时库，结束清理，不是实际教材修订。截图、PDF与JSON中的课堂和教师输入均为SYNTHETIC，不代表真实教师审核；教材摘要来自已上传原页，不是模拟教材。

本机真实SQLite完整备份与`.local/backups/p34-after.kb-full-backup.json`比较相同，保留23条知识、27版本、50声明、0审核决定。未提交本地数据库、扫描页、模型、视频、学生资料或私有反馈。

## 交付物与限制

- `before.png`：在基线代码上重新运行原浏览器脚本获得，展示原占位草稿；不是拼接示意图。
- `after.png`：修复后L05，王树本教材事实与编辑面板。
- `after-li.png`：李乡状PDF39事实与课程建议分栏。
- `stale-reference.png`：临时版本变化后的历史失效提示。
- `acceptance.json`：实际浏览器验收标志和初始库计数。
- `L05-print.SYNTHETIC.pdf`：浏览器实际打印，教师目标为明确标记的测试修改。
- `L05-plan.SYNTHETIC.json`：原JSON导出接口返回，包含版本及pending历史。
- `L05-review-draft.md`：当前真实教材摘要组成的教师审阅样稿，没有假造教师意见。

浏览器环境为Linux Chromium，不等于已在真实Mac Safari/Chrome上完成教师试用；没有逐条专项签署、真实学员评价、真实视频识别或正式教案批准。仍须实际专项和现场教师复核；离线副本不会自动更新。原24主题、SQLite历史及审核保护、视频和教学闭环相关回归均包含在上述完整测试中。
