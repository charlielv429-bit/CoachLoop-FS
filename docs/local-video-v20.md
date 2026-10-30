# CoachLoop-FS V2.0：本地视频、未认证审核与反馈草稿

## 已实现与真实边界

基于 main `25215992fe8324f621b2a10f143b6d3ea2036978`，保留V1.1的24主题备课及PR #12课堂演示。同一 `http://127.0.0.1:8767` 页面增加“智能备课 / 视频动作分析 / 训练反馈”，不创建另一个公开服务，不连接Coze、付费模型或数据库。

本轮已真实执行 MP4和MOV的上传→FFmpeg→MediaPipe→特征→V4事件→V5状态操作→反馈→导出/清理；真实Chromium也完成整条MP4网页链路。**这不是花滑动作准确性验证，也不是已认证教练系统。** 测试用实拍素材是公开深蹲视频，不是学生视频或花滑专业示范。审核点击来自自动化验收，明确标为 `local_unverified`，没有伪造真人教练资格。

真实视频功能只挂本地console工厂。Cloudflare课堂的路径白名单仍拒绝所有 `/api/v2/video/*` 和 `/video-console.js`；页面中的两个新导航在课堂模式禁用，不加载视频脚本。测试是在合法HTTPS代理上下文、已登录课堂会话下验证拒绝，不以错误代理头的403替代此验证。

## 原有流水线审计

| 模块 | 实际支持与复用情况 |
| --- | --- |
| `tools/video_analysis/pose_extractor.py`、`extract_video.py` | 真实磁盘视频→MediaPipe Tasks `PoseLandmarker` VIDEO模式、单人33点→原有特征；缺失保留，不插值。旧注释曾写1.2，本轮实测版本是0.10.32。新增可选`include_keypoints=False`，仅本地适配器显式取用原始关键点；通用序列化排除此字段，旧参数与输出字段保持。 |
| `schemas.KeypointDataset`、`mp_mapping.py` | 数据结构本身可携带 `is_mock=false`；真实入口用它转录实际关键点。它不是只支持mock的算法。 |
| `keypoint_io.py`、`run.py` | JSON文件读取入口仍只接受 `is_mock=true` 和 `mock://`，不把其合成测试冒充真实视频处理。本轮不绕过这个入口的保护。 |
| `features.py`、`geometry.py` | 同一套肩/髋/膝/踝二维几何，膝角、躯干倾角、髋踝相对偏移；缺失/退化/非有限数据有质量标记。没有新建姿态估计或特征算法。 |
| `event_detection.py` | 复用居中平滑、稳健基线、探索性偏离量及连续事件合并；保留低可见度、未检出、疑似突跳等标记。阈值不等于技术错误标准。 |
| `event_review.py` | 复用稳定事件ID、pending/confirmed/normal_movement/tracking_error/uncertain及追加历史；适配层额外固定服务端操作者、时间、序列和幂等校验。 |
| 旧 `review_ui.py` | 原本是独立本地服务与JSON文件；未直接嵌入其全局共享文件或改写它。新的会话隔离界面复用同一V4/V5算法。 |
| `agents/postlesson_agent.py` | 原模块是数据库、mock数据域与可信身份查询边界，不能用于把真实本机视频改标mock或伪造authenticated。因此新增更保守的本地反馈适配层，原模块及数据库保护不变。 |

```mermaid
flowchart LR
  B[本机浏览器独立会话] --> F[Local FastAPI / 8767]
  F --> U[私有临时上传]
  U --> N[FFprobe校验 / FFmpeg规范化]
  N --> M[隔离进程 MediaPipe Tasks]
  M --> E[既有特征与V4候选事件]
  E --> R[V5追加审核：本地未认证]
  R --> D[反馈草稿：技术错误未评定]
  D --> X[用户主动导出 / 任务清理]
```

## Mac 最简启动

1. 取得此分支完整代码，先在旧服务终端 **Ctrl+C**。首次需要已安装的FFmpeg/ffprobe（已有Homebrew可安装免费 `ffmpeg`），以及项目现有Python 3.12+。
2. 首次双击 **`scripts/setup_local_video.command`**：仅在独立 `.venv-video` 安装 `requirements-video.txt`，从Google官方固定版本URL下载模型并核对SHA256。不修改主 `.venv`，不启动服务、不上传视频。已有未知模型不会静默覆盖；已有匹配文件仅校验本地哈希，不额外证明其官方来源。网络、架构或依赖不兼容时退出。
3. 双击原 **`scripts/start_prelesson_console.command`**，打开 **http://127.0.0.1:8767**，选择“视频动作分析”。缺少视频环境时页面明确提示，原备课仍可使用。
4. 选择有合法使用权并获必要隐私授权的单人侧面视频，勾选三个声明，选择观察侧，点击“上传到本机并分析”。完成后可播放规范化预览、查看观测骨架、点击事件跳转、提交本地未认证审核、生成反馈并主动导出。
5. “取消并清除本机任务”删除本任务媒体与服务端记录；不删除您自行选择的原文件或已下载导出。刷新页面会恢复同一浏览器尚未过期的任务；处理失败可清除后重新上传。结束后 **Ctrl+C**，停止源站并清理所有本次临时任务及工作进程。

本轮实际运行环境是Linux/Python3.12、MediaPipe0.10.32、OpenCV-contrib4.12.0.88、Pydantic2.12.5和CPU推理。**没有声称在用户Mac或Safari上实测成功**。Mac芯片/系统须有这些版本的可用wheel；旧版Intel设备、系统库、网络下载和编解码兼容性需本机确认。安装器失败不会把mock当真实结果回退。

## 视频输入、质量和资源边界

- 原始上传≤25MiB，非空MP4/MOV，必须有可识别ISO-BMFF `ftyp`；部分旧式MOV不支持。后缀/MIME不是唯一判定，后端再检查实际容器与编码。
- ffprobe检查一条视频流、时长(0,60]秒、帧率(0,60]、宽高16–1920且总像素≤2073600。允许h264/hevc/mpeg4/h263/mjpeg；依赖本机FFmpeg支持，不承诺所有MOV/HEVC变体。
- 源文件名不传到服务端；浏览器只传格式枚举、固定声明和字节，服务端生成UUID目录与固定文件名。接口不接受视频URL、磁盘路径、模型路径或关键点JSON。
- FFmpeg强制MOV族解复用，协议仅file/pipe，关闭MOV外部数据引用，去掉音频和元数据。输出最长60秒、最大边720像素、不高于12fps、≤720帧的H264预览；解码/转换失败安全退出。**帧号属于分析预览，毫秒时间对应规范化预览，不是原片逐帧精确测量。** 可变帧率、旋转、重采样与投影误差必须复核。
- 原上传在规范化后立即删除，失败时也清理。规范化预览、关键点和审核不自动归档：任务20分钟到期，后台清理最多约10秒调度延迟；每次请求也检查过期。会话最长30分钟，未开始上传的保留任务120秒到期。
- 每浏览器最多1任务，进程最多8任务/16视频会话；推理单工作进程排队。上传流总超时120秒，ffprobe15秒、转换60秒、工作进程180秒；POSIX CPU/文件大小限制作为附加保护，不宣称完整OS沙箱。
- 预览和导出仍可能包含面部或可识别运动信息，用户必须保管；本系统不做人脸识别、自动匿名化或法律授权认证。下载文件/浏览器已收到的数据无法被服务器远程抹除。

检出比例只是是否检出人体，不代表几何可靠、技术正确或安全。骨架绘制的可见度0.5只是UI显示假设；V4可见度0.75、角度/偏移阈值和平滑窗口也是工程探索参数，非专业合格线。单人声明不等于系统已验证人物数量或身份，多人视频不在本版本支持范围。

## 会话、安全与审核语义

- 保留原LocalBoundary的真实loopback、精确Host/Origin、HttpOnly/SameSite会话、CSRF、自报Authorization/代理头拒绝及WebSocket限制。仅为特定上传路径增加video/mp4与video/quicktime流式分支，其余POST仍要求JSON。
- 另签发独立视频Cookie和服务端操作者随机标识；每个任务校验其所有者。其他浏览器即使猜到任务UUID，也不能读结果、播放、审核、删除或生成反馈。没有使用前端自报角色、姓名或时间。
- 源站明确 `proxy_headers=False`，请求并发32、保活5秒、关闭宽限5秒。CSP只在本地增加同源/blob媒体，CORP同源、no-store等保护保留。Cloudflare边界未放开媒体或视频接口。
- 私有临时目录权限700、上传文件600；媒体通过已打开文件描述符按受控单Range读取，避免删除竞态抛出服务器磁盘路径。错误消息不回显解码器日志、路径、文件名或凭据。
- 审核调用只允许状态/备注/期望序列/幂等UUID；服务端记录UTC时间与本地会话操作者。原始事件快照不可从HTTP修改，同键同动作不重复追加，冲突返回409，历史最多256次动作。临时历史不是永久数据库审计，须主动导出需要保留的记录。
- `confirmed` = 本地操作者报告确有可观察变化，**不是技术错误**；`normal_movement`也只是未认证的本地判断。pending、tracking_error、uncertain不进入动作评价依据。
- 反馈中的 `reported_observations`明确未认证；`trusted_observations=[]`、`authenticated_coach=false`、`review_verification=local_unverified`、`technical_error_assessment=not_assessed`。始终draft、requires_teacher_review=true、knowledge_status=unverified；候选练习是教师选择的保守复习/复核提示，不是视频自动诊断或成绩。

本机Cookie会话不是专业教练认证，也不是同一Mac上的恶意进程/不同本地端口服务的安全隔离。使用可信Mac账户与浏览器，不反向代理真实视频。公网、多用户身份、真实学生试点、专业教练认证、数据库归档须单独审计，本轮未实现。

## 本地接口

所有接口均受LocalBoundary及视频会话约束，**没有挂到生产main或Cloudflare课堂**。

| 方法与路径 | 用途 |
| --- | --- |
| GET `/api/v2/video/capabilities` | 文件/工具前置与资源限制；不声称仅凭文件存在就认证运行兼容性 |
| POST `/api/v2/video/jobs` | 验证合法使用/隐私/单人侧面声明，创建当前会话任务 |
| POST `/api/v2/video/upload?job_id=UUID&format=mp4或mov` | 二进制流上传，校验并进入本机处理 |
| GET `/api/v2/video/current` | 刷新后恢复本浏览器当前任务 |
| GET `/api/v2/video/status?job_id=UUID` | queued/running/ready/failed与质量摘要 |
| GET `/api/v2/video/result?job_id=UUID` | 真实分析、关键点、V4候选事件及V5未认证审核导出 |
| GET `/api/v2/video/media?job_id=UUID` | 同会话规范化预览，支持单字节Range |
| POST `/api/v2/video/review` | 追加审核、序列冲突与幂等检查 |
| GET `/api/v2/video/feedback?job_id=UUID` | 保守反馈草稿，不访问数据库 |
| POST `/api/v2/video/delete` | 取消工作进程并清除私有任务 |

## 真实素材、模型来源与证据

测试视频：TensorFlow官方 `tfjs-models` 仓库的 `pose-detection/test_data/pose_squats.mp4`，依据仓库根目录Apache-2.0许可证用于本地技术验证；没有另行声称取得演员/教练认证或用于真人课堂结论。

- [视频来源（固定提交）](https://github.com/tensorflow/tfjs-models/blob/c731b9ebbd6f4c9e8bf99b0df76bbdbf9c25b07f/pose-detection/test_data/pose_squats.mp4)
- [Apache-2.0许可证](https://github.com/tensorflow/tfjs-models/blob/c731b9ebbd6f4c9e8bf99b0df76bbdbf9c25b07f/LICENSE)
- SHA256 `ea9151e447b301985d5d65666551ef863b369a2e0f3a71ddd58abef2e722f96a`；508341字节；13秒、5fps、720×1280。MOV验收是同一许可片段无损重封装，没有以合成关键点替代实拍。

模型：本轮从公开GitHub镜像取Google Pose Landmarker Full任务包，镜像README声明为未修改的Google模型。文件SHA256 `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`，9398198字节。镜像固定提交 `a22a9520d07e2ff351fbcf2c01dccff5713471a9`，[来源与声明](https://github.com/BaratovAbdulaziz/pose-detection-models/blob/a22a9520d07e2ff351fbcf2c01dccff5713471a9/README.md)。

**本轮尚未独立直连Google官方源比对该权重**，不能把镜像声明当密码学来源证明。Mac准备脚本只从 [Google官方固定版本](https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task)下载并核对更新后的用户Mac核验哈希，不自动回退镜像；模型使用仍须遵守上游条款。2026-10-30 用户Mac通过 HTTPS 独立下载该URL，下载文件与其本地模型 SHA-256 同为 `5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1`，`cmp` 输出 `OFFICIAL_FILE_MATCH`，MediaPipe 0.10.32 实际加载输出 `MODEL_LOAD_OK`。该证据来自用户Mac截图，不是本次GitHub执行环境的独立下载；HTTP响应头已由用户Mac保存至 `/tmp/coachloop-model-headers.txt`，尚未逐项审阅；模型内部元信息也尚待单独审计。旧 `4eaa5eb7…` 来源于第三方镜像，仅保留为历史记录，不可再作为官方URL的预期哈希。

实际结果：65帧/65帧检出、18条候选变化；仅是本视频与本版本的链路结果，不是准确率。真实浏览器证据位于 `docs/local-video-v20-evidence/browser.json` 与 `video-ui.redacted.png`。截图遮蔽原片、骨架与具体事件细节；视频、模型、逐帧关键点和真实逐事件导出未提交。`review_action=automated_local_unverified`明确审核是自动化验收操作，不冒充真实教练。

## 自动化与专业待确认项

正式测试 `tests/test_local_video_v20.py`，区分合成契约测试与显式真实素材验收。设置合法素材路径 `COACHLOOP_TEST_VIDEO` 后才执行真实MP4/MOV推理；缺素材时该项跳过，并明确不构成真实视频验收。完整测试还需隔离PostgreSQL环境，参照既有数据库文档，不连接生产数据库。

真实浏览器可选命令：设置 `COACHLOOP_TEST_VIDEO` 后用现有主环境执行 `scripts/verify_local_video_browser.py`，需Chromium和websockets测试工具；不自动下载模型或视频，不提交其私有导出。测试容器的浏览器无沙箱参数不用于正常Mac服务或公网部署。完整计数及命令见本目录 `acceptance.json`。

专项教练仍需确认：侧面机位、左右侧/镜像及投影限制，低帧率重采样影响，V4探索阈值与可见度参数，真实花滑动作观察体系，何种证据足以支撑教学反馈，以及候选练习与年龄/技术水平/冰场安全的适用性。本轮没有训练新模型、验证花滑准确率、认证真人教练或批准真实训练报告。
