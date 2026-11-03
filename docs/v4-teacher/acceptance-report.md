# V4教师工作台验收报告

## 基线与复用审计

fetch后确认PR #22已合并，main为134c430c1b49af8927f1f55a8a90ae49a1431567。独立分支feat/v4-teacher-console。
原首页同时展示V1.1主题、课次参数、知识编辑及多个JSON区；本轮将原页面原样保留在/advanced，并给根路径增加独立教师界面。

| 现有模块 | 本轮复用方式 |
|---|---|
| L01–L08与45分钟 | 仍调用原plans/draft、plans/edit、history；9/29/7及资源/先修暂缓不改 |
| 已有课程草稿 | 读取PR #21 course-inventory的TeacherEdits并校验，所有载入文字保留待审性质 |
| SQLite与审核 | 复用Archive、EvidenceBundle、snapshot、restore_full的既有事务、绑定校验与空库限制；只新增只读计数 |
| 视频/候选事件 | 复用既有video-console.js及全部本机API，新增界面时间轴导航；没有修改MediaPipe、几何或V4/V5 |
| L05教师反馈 | 调用PR #22 loops/link/edit/confirm/export/history；仍双会话隔离，证据变化使确认失效 |
| V1.1与高级研发 | 保留原HTML/JS和API；旧浏览器脚本明确访问/advanced，不更改主题算法或API契约 |
| Mac启动 | 现有.command增加--open-browser；服务bind成功后才尝试打开loopback地址，浏览器失败不停止服务 |

## 实际测试结果

- 完整回归：`PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider` → **1002 passed, 193 skipped, 1 warning，106.97秒**。
- 新增16项教师适配测试通过：空库/并发初始化、严格同意、禁止外部包、字节完整性、校验后期失败回滚、已有资料保护、版本重启读取、pending保护、可读HTML/转义/私有打印、CSRF/代理和课堂拒绝，以及自动打开浏览器失败后仍可访问的真实启动器测试。
- 本轮较早的定向回归51 passed；打印过期中文HTML补强后定向16 passed（15项当时V4测试＋真实HTTP启动器测试）。最终完整回归包含新增浏览器启动钩子用例和全部16项V4测试。
- 193跳过仍是191项未配置专用PostgreSQL、2项缺授权真实视频；不算通过，不由合成演示替代真实推理。
- 1项警告为第三方cozeloop的Pydantic配置弃用，与本轮UI无关。
- JS语法、Mac.command bash语法与git diff --check通过。
- 默认真实SQLite与P3.4完整备份逐项一致：23 IDs/27版本/50声明/0决定。所有初始化和浏览器写入均使用临时库，没有覆盖用户本地数据。

首轮完整回归的2个失败是旧测试把V3管理区/console.js固定断言在根首页；按产品要求将旧界面断言移到/advanced并新增teacher.js首页断言后重跑通过，没有放宽安全断言。
旧V1.1浏览器脚本曾使用未限定表单的同名字段选择器，实际选中了前置L05表单；已明确限定#lesson-form，原主题行为和全部断言保持，浏览器复测通过。
浏览器验收还修正了自动化弹窗用户手势、异步选项等待和后台截图窗口焦点，未以静态截图替代真实操作。

## A–F真实浏览器操作

```sh
PYTHONPATH=src .venv/bin/python -B scripts/verify_teacher_v4_browser.py --output-dir work/new-v4-evidence
```

--output-dir必须全新；Linux Chromium、临时空SQLite、故意不存在的模型/视频Python路径、合成课堂条件/关键点/教师文字，未使用真人学生或教师意见。

| 场景 | 实际操作与结果 |
|---|---|
| A首次空库 | 首页显示初始化说明；未勾选不会写入；明确同意后23/27/50/0，已有数据按钮禁用，后端重复和并发初始化拒绝 |
| B打开L05 | 首屏四入口，自动载入L05，8课卡完整；无须人工输入人数等研发参数，预设明确演示/待确认；已有来源与pending可见 |
| C修改/导出 | 点击正文“修改这一项”聚焦目标编辑；未保存不能打印；保存版本2后打开真实HTML打印窗口；实际Page.printToPDF生成3页PDF，并从PDF提取验证编辑文字、K011及待审核标记；普通页无pre/裸JSON |
| D合成闭环 | 模型缺失仍能显式合成演示；时间轴、原事件复核、L05匿名观察、示例标识、草稿/本地自报确认、事件变化后退回草稿均实际操作通过 |
| E真实限制 | 缺独立视频环境/模型如实提示且真实上传分析按钮不可用；专项来源未审持续标示；资源不足预设生成暂缓，无伪装真实学情或正常实操 |
| F原功能 | 高级入口打开原24主题和八课。另运行原课次、PR #22闭环、V1.1自适应与知识库浏览器回归，均通过 |

原浏览器命令：

```sh
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_teaching_loop_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_adaptive_prelesson_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_curriculum_v3_browser.py
```

原课次验证编辑/历史/实际JSON下载与资源暂缓；原闭环验证修改和失效/私有恢复；V1.1验证24主题筛选、中英文搜索、人数变化、教师编辑、XSS纯文本和导出；知识库验证新增、版本历史与真实备份下载。

## 可展示成果

- 7张.SYNTHETIC.png：实际新版首页、L05、知识、缺模型、事件、反馈和资源不足页面。
- L05-print.SYNTHETIC.pdf：真实浏览器生成的3页合成教案PDF，不是教材扫描或正式教案。
- acceptance.json：A–F机器记录，明确actual_Mac_test=false、actual_teacher_review=false、real_video_inference=false。

## 实际修改范围

- README.md与docs/v4-teacher/*：教师说明、验收、截图及PDF；.gitignore只为这一份合成打印PDF设单文件例外，教材PDF仍排除。
- src/integrations/prelesson/console_static/teacher.html、teacher.css、teacher.js：四入口、八课载入、自然中文教案/反馈、知识查看与显式初始化。
- teacher-print.css、teacher-print.js：浏览器原生打印，不声称生成Word或强制保存PDF。
- src/integrations/prelesson/teacher_api.py：固定本地包初始化、已有草稿载入和会话约束的转义HTML打印；无任意路径或任意包输入。
- src/integrations/prelesson/console.py：教师根首页与高级路由、固定静态资源、既有CSRF/签名会话及打印错误中文提示；课堂/production不挂新增路由。
- src/integrations/curriculum_v3/persistence.py：只增加事务内只读计数；既有恢复事务和全部表结构不改。
- scripts/run_prelesson_console.py、start_prelesson_console.command：成功启动后尝试打开本地浏览器，保持loopback、proxy_headers=False和原限额。
- scripts/verify_teacher_v4_browser.py及5个既有本地浏览器脚本：真实A–F与高级入口回归，选择器限定正确表单。
- tests/test_teacher_v4.py、test_curriculum_v3.py、test_prelesson_console_http.py：新增验收并保持原安全检查；旧首页位置断言按新入口调整。

## 未完成与专业边界

本轮不是Mac签名安装包。首次主环境依赖仍需维护者准备，不能承诺任意新Mac无需安装即可运行；教师日常使用改为双击启动和浏览器操作，无须输入命令或理解JSON。
尚未真实Mac/Safari、实际教师、获授权花滑视频或系统打印对话框验收；未增加付费模型、Agent框架、评分、数据库架构或学生账号。
真实视频仍只在本机，未经专项审核的资料继续pending；合成意见不是真实教师反馈。未自动合并或部署。
