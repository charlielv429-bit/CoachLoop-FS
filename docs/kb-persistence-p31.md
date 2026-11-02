# P3.1 本地共享知识库持久化

基线main=894b6bfbbdc18c9750b0079f7ab6982f5a1380ba，已包含PR #15/#16（含教案会话隔离修复）。
独立分支 feat/p3-1-local-kb-persistence，只保存知识条目、来源信息和历史版本。
不新增AI功能、PDF解析、OCR、评分、生产数据库表或教练认证。

## 存储选择与位置

标准库SQLite单文件，不增加依赖。比直接覆盖JSON更容易提供原子追加、多进程写入互斥及失败回滚。
正式本地启动器默认使用：仓库根目录 `.local/coachloop-kb/knowledge.sqlite3`。
在当前云端工作区对应 `/workspace/CoachLoop-FS/.local/coachloop-kb/knowledge.sqlite3`。
可显式指定独立目录：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_prelesson_console.py --port 8767 --kb-dir /absolute/private/coachloop-kb
```

不读取生产DB环境变量、不使用SQLAlchemy/生产连接、不修改mock隔离。
`create_console_app()`默认仍是无磁盘写入的嵌入/测试工厂；启动器显式注入SQLiteRegistry。
自定义嵌入服务需调用 `create_console_app(knowledge_store=SQLiteRegistry(directory))`；界面展示实际存储类型，避免误以为内存数据已持久化。

目录必须由当前OS用户拥有且权限恰为0700，DB文件0600，拒绝目录路径中的符号链接、DB硬链接/符号链接和不安全旁文件。
仅适用于支持POSIX权限的Linux/macOS本地文件系统；不支持Windows权限模型、网络共享磁盘或多主机并发。
文件是未加密的本地资料库；同一OS账号拥有文件读取和管理权限，不承诺抵御该账号下的恶意程序。
SQLite采用DELETE回滚日志、synchronous=FULL及内存临时表，事务中可能出现0600的 `knowledge.sqlite3-journal`。
目录、SQLite文件/旁文件和推荐JSON备份名称均由.gitignore排除；不提交数据库、真实教材、PDF或学生资料。

## 权限与数据生命周期

KB-S/KB-P/KB-A/KB-E沿用明确共享的知识库：所有已授权本机控制台会话可检索、追加和备份共享条目。
这不是教师私有笔记库，不能放学生身份、健康资料、私有教案备注、凭据或教材PDF原件。
界面与API存储说明均明确共享范围。没有新增私有知识条目类型或可被普通用户自报的权限字段。

私有教案仍仅保存在进程内存，按独立签名浏览器Cookie隔离；不写入SQLite或知识库JSON。
其他会话即使知道plan_id也不能导出、查看历史或修改。教案及视频仍按原生命周期清理，重启不会恢复这些私有记录。
知识库关闭只释放连接和内存缓存，绝不删除磁盘历史；重启重新校验和读取。

## 数据完整性与审核保护

SQLite仅存追加版本（knowledge_id/version/payload），主键唯一，触发器拒绝UPDATE/DELETE。
写入在BEGIN IMMEDIATE事务内重读最新历史、校验版本连续性与容量，再整批追加；任何失败回滚，无部分覆盖。
多个本地进程/实例指向同一目录时可看见已提交变化，竞争同版本仅一个成功，另一返回409。
保留现有200条目、500累计版本、900KiB完整JSON导出上限，以及1MiB导入请求上限；重启不会清空容量。
达到上限时先备份，再显式选择新的知识库目录归档，不能用重启绕过容量或覆盖历史。
启动和每次读取都严格校验Schema、状态、版本连续性及行ID一致性；损坏/未知SQLite版本拒绝启动，不自动重置或降级为空库。
运行时存储故障返回脱敏503；版本或容量冲突409；非法请求422/超限413。原数据保留。

来源状态仍仅pending/submitted/rejected，专项状态仍仅pending/requested/rejected。
submitted需要非空来源ID、标题和定位，但不等于正文核实。verified/approved/certified及伪造审核人字段均拒绝。
普通JSON导入不能升级审核状态；篡改DB后写入伪造认证记录也不能通过应用启动校验。
当前无可信专业身份审核渠道，所有资料仍待审核，备课正式专项依据与动作指导仍为空。
本地SQL文件管理者能改普通内容，应用不把文件权限当专业认证。

## 备份、恢复与离线审核

浏览器：展开“V3.0 · 8课次课程目录与知识库管理”。
- “备份全部版本 JSON”：下载 `coachloop.kb-backup.json`，含四类条目、来源及全部版本。
- “导入未审核知识”：选择备份JSON，按连续版本整批追加；恢复完整备份请使用新的空知识库目录。
- 已有ID/版本冲突整批409，绝不覆盖。非法格式/脚本/状态/重复键整批拒绝。
- “导出离线待审核材料”：下载 `coachloop.kb-review.json`，含内容/来源快照及审核清单，不含私有教案。

离线工具（建议先停止控制台），使用专用文件扩展名避免误提交，输出文件必须不存在：

```sh
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/coachloop-kb backup --file .local/backup.kb-backup.json
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/restored-kb restore --file .local/backup.kb-backup.json
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/coachloop-kb review --file .local/offline.kb-review.json
PYTHONPATH=src .venv/bin/python scripts/run_prelesson_console.py --kb-dir .local/restored-kb
```

CLI JSON输出为0600，排他创建不覆盖、不跟随已有文件链接，刷新写入后fsync；恢复限制1MiB，严格拒绝重复键、非法状态及冲突。
导出读取完整事务快照，可与正常写入并行，但建议停服执行管理操作以便核对。
离线审核材料不是可导入的认证结果：直接导回知识库会被拒绝。专项同学在应用外核查原文、定位、支持关系、适用范围和安全要求；后续可信审核通道另行开发。
浏览器下载目录及下载副本权限由浏览器/OS管理，用户应移入私有目录并保管；不会随退出服务自动删除。
备份是逻辑JSON，不要在运行时仅复制SQLite文件。恢复后应逐项核对条目数量、来源和历史版本。

## 删除

应用不提供在线单版本删除，以保留可追溯历史。
如需清空全部知识库：先停止所有指向该目录的控制台/CLI，确认备份，再手工删除所选专用知识库目录中的
`knowledge.sqlite3`及可能存在的同名 `-journal/-wal/-shm` 文件，或删除整个专用目录。
下一次启动创建空库。不要删除仓库其他目录；不要在服务运行中删除DB。
已下载JSON和用户另存备份要分别删除；本轮未执行任何用户数据删除。

## 验证

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_curriculum_v3_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
node --check src/integrations/prelesson/console_static/curriculum.js
git diff --check
```

新增测试使用临时目录和明确模拟条目；真实启动器进程先写入，再退出重启，验证仍能读取相同历史。
浏览器验收启动器均显式选择临时知识库目录，不向用户默认持久库写入模拟数据。
额外验证版本恢复、真实SQLite事务失败回滚、多实例冲突、私有教案隔离、错误脱敏与Git忽略规则。

本轮实际结果：906 passed, 193 skipped, 1 warning（63.94秒）；新增16项持久化测试全部通过。
193跳过仍为191项未配置隔离PostgreSQL与2项未提供获授权真实视频，不计为通过。
第三方cozeloop存在Pydantic旧配置弃用警告。
两个Chromium脚本通过；知识库脚本实际下载并解析完整备份和待审核材料，L05脚本保留教案实际下载验收。
浏览器启动时补充等待page target出现，避免Chromium调试端口就绪但页面尚未建立的时序问题。
JS语法、git diff空白检查及本地数据Git忽略规则均通过。
未改生产main、24主题算法、45分钟备课逻辑、私有教案机制、真实视频算法或数据库mock隔离。
当前限制：知识库是显式共享资料库，没有教师私有知识空间或可信专业认证；私有教案不持久化；
存储只支持POSIX本地文件系统，历史容量限制保留，需人工备份和选择独立目录归档。没有自动备份调度、PDF解析或OCR。
