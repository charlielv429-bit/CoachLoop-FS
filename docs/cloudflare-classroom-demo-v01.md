# Cloudflare Quick Tunnel 课堂演示（V1.1）

## 状态与边界

基线 main `dacb0c6`，已包含 PR #10 与 V1.1。新增独立且显式开启的课堂模式，复用24主题、自适应教案Agent及原HTML/CSS/JS。原 `127.0.0.1:8767` 本地启动器与 `LocalBoundary` **未修改**；默认不创建公网入口。未修改生产main、Coze、视频、数据库或迁移。

**当前仅通过本地 HTTP、真实浏览器与本地 HTTPS 模拟代理验证；未通过真实 Cloudflare 公网验收，也没有可交付的已验证公网网址。** 本执行环境未安装 cloudflared；Cloudflare文档站 CONNECT 被受管网络策略403拒绝，TCP网络无外部授权。本轮没有启动真实隧道、绕过网络策略或连接用户Mac。

Cloudflare客户端实际创建的随机地址与访问码只在教师自己的Mac启动时产生。测试文件中的 `synthetic-*` / `simulated-*` 地址均为测试标记，不是在线服务。Cloudflare无账号Quick Tunnel不保证可用性，课堂前须用手机实际验收，不能只看“隧道创建成功”。

## Mac 最少操作

首次准备（一次性）：

- 使用已能运行V1.1的项目Python 3.12+环境。
- 安装官方 `cloudflared` 客户端。已有Homebrew可执行一次 `brew install cloudflared`；或按[Cloudflare官方下载说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)安装。启动器也检查Apple Silicon和Intel Homebrew常用路径。不自动下载执行脚本、不登录账户、不创建付费资源。
- 如需自动生成二维码，在项目现有虚拟环境安装可选 `qrcode>=8,<9`（仅生成SVG，无新服务器）。例如项目已有pip时 `.venv/bin/python -m pip install 'qrcode>=8,<9'`；使用uv管理环境时 `uv pip install --python .venv/bin/python 'qrcode>=8,<9'`。这是 `pyproject.toml` 的可选 `classroom` extra；不影响纯本地模式。没有该包仍可分享网址，终端明确提示未生成二维码。

日常课堂：

1. Finder双击 **`scripts/start_classroom_tunnel.command`**。这是明确开启临时公网模式的动作。保留终端，等待随机HTTPS网址、单独的课堂访问码和二维码路径。Mac会尝试打开仅含网址的二维码SVG。
2. 将网址或二维码分享给课堂设备，**访问码单独告知**，不要写进链接、二维码、Git、截图或聊天记录。手机/iPad/电脑打开网址，输入访问码并确认仅使用模拟数据。班级标签使用 `MOCK-` 开头的大写ASCII标识；不要输入真实姓名、健康记录、视频或账号凭据。
3. 选主题、填写合成教学条件和已掌握技能，生成并下载草稿。建议教师先使用手机蜂窝网络完成一次生成，确认不是只在Mac局域网可见。
4. 结束后双击 **`scripts/stop_classroom_tunnel.command`**，或原启动终端 **Ctrl+C**。停止脚本等待锁释放后才报告停止确认，不按旧PID杀进程。关闭浏览器不是停止服务。

课堂模式在另一个随机 **127.0.0.1端口**运行，供cloudflared转发；不占用8767，因此原本地界面可保留。课堂模式的原始HTTP端口不是供浏览器直接使用的入口，直接访问会拒绝。没有公网绑定、路由器端口转发或第二种技术栈。

默认最长90分钟，可用 `run_classroom_tunnel.py --enable-classroom-tunnel --minutes 30`设为5–180分钟。每个浏览器会话最长60分钟，不超过课堂结束时间。重启生成新地址、访问码和会话；旧Cookie不能进入新课堂。

## 认证、Host、Origin 与代理信任

- 访问码由`secrets.token_urlsafe(24)`产生，约192位随机强度；只存内存并在教师启动终端显示，不写入环境、命令行参数、文件、网页或日志。共享码仅授权模拟草稿生成，不认证教师、教练、审批或审核状态。
- 每次成功登录生成独立随机会话；Cookie为 `__Host-coachloop_classroom`，`Secure`、`HttpOnly`、`SameSite=Strict`、`Path=/`、无Domain。匿名GET不签发会话，不可通过刷新登录页跳过认证。退出、到期及关闭进程会撤销会话。
- Quick Tunnel输出的精确 `https://<随机子域>.trycloudflare.com` 仅能固定一次；拒绝占位、用户信息、端口、路径、查询、通配域和其他域。未固定域名前，所有HTTP请求返回503。
- 源站只接受真实peer `127.0.0.1`、原始HTTP scheme；Uvicorn明确 `proxy_headers=False`，不能让伪造X-Forwarded-For重写客户端身份。
- `Host`必须唯一且等于本次固定公网域；`X-Forwarded-Proto`必须唯一且为`https`。`CF-Visitor`如存在只能表示HTTPS；`X-Forwarded-Host`如存在必须匹配固定域；拒绝`Forwarded`、调用者Authorization及重复/矛盾安全头。
- 启动器不设置`--http-host-header`，保留公网Host。Cloudflare官方源代码确认只有配置hostHeader时才重写Request.Host；本模式不靠删除Host检查适配代理。若未来客户端版本实际头行为变化，须以脱敏证据重新确认，不能放宽成任意Host/Origin。
- `X-Forwarded-For`、`CF-Connecting-IP`、`X-Real-IP`不提供用户身份，也不决定限流额度，转交应用前移除。转发头只是受限loopback代理链的元数据，**不宣称等同于经密码学认证的Cloudflare身份**。具有同一Mac用户权限的其他程序不在此隔离边界内。
- 所有POST（含登录、退出）都要求唯一精确HTTPS Origin、唯一`X-CoachLoop-Console: 1`与JSON；受保护路由还需有效会话。只允许从聊天分享链接打开惰性的根文档导航；跨站fetch、iframe和操作仍拒绝。没有跨域放行。
- 路径/方法白名单；WebSocket关闭1008；旧`/run`、主服务课前V1、数据库导入、文档等均不可访问。CSP、X-Frame-Options、no-store、nosniff、no-referrer保留；HTTPS课堂设置短期HSTS。

这不是生产多租户平台：不防御获得同一Mac账户权限的进程，也不提供校级账户、审计认证或抵御大规模DoS的承诺。公开链接和课堂码应只在有限课堂分享。

## 限流、数据与输出

- 进程全局最多900次请求/分钟、10次登录尝试/分钟、30次生成尝试/分钟；每个已认证会话最多6次生成尝试/分钟。使用单调时钟和线程锁，不接受请求体/代理IP自报的限流身份。最多64个有效会话。
- 达限返回429与`Retry-After: 60`；共享码课堂的全局额度可能因错误重试或恶意流量耗尽，这是基本限流的明确限制。重试前等待，不通过伪造IP或反复登录绕过限制。
- 输入限32KiB，包含流式及虚假Content-Length情况；复用严格JSON重复键/非有限数值和脱敏错误保护。生成异常只返回通用503，不回显内部错误、访问码或教案。
- 接收 `ClassroomRequest`，在原 `AdaptiveRequest` 上要求 `data_domain="mock"`、严格布尔`is_mock=true`及`MOCK-[A-Z0-9_-]{1,60}`班级标签；拒绝pilot、false、数字1伪装布尔、真实班级标签及额外身份/批准字段。**标签和勾选只是用户的模拟声明，不是自动隐私检测或匿名化，禁止把真实数据改标MOCK。**自由文本仍须教师确保完全合成。
- 返回 `ClassroomResult`：`data_domain=mock`、`is_mock=true`、`human_review_performed=false`和受保护`draft`。网页导出保留`demo_data_domain=mock`、`is_mock=true`、`human_review_performed=false`；未标成真实审核或真实训练记录。
- 24主题、七要素、45分钟、先修与资源限制、教师修改和导出复用既有Agent。结果始终draft、requires_teacher_review=true、knowledge_status=unverified；无心率预测、没有数据库写入，不伪造正式教学依据。

## 启停与凭据隔离

监督程序先持有私有状态目录的排他锁，再用预绑定loopback socket启动源站，然后启动自己唯一的cloudflared子进程。隧道输出只解析经验证的候选网址，原始日志不转存；源站在域名固定前关闭。

cloudflared使用单独空配置，`--no-autoupdate`、`--protocol http2`及仅loopback的随机metrics端口。不会采用已有named tunnel配置；子进程环境移除TUNNEL/Cloudflare账户、数据库和本项目凭据变量，保留正常网络代理及CA信任，不进行TLS绕过。

私有运行目录为 `~/Library/Caches/CoachLoop-FS/classroom-<项目路径摘要>/`，权限700。只保存无访问码的`origin.json`、网址二维码、空配置及锁；拒绝symlink目录。二维码由本机生成，没有第三方二维码网站。停止控制使用私有STOP文件和排他锁，绝不依赖缓存PID；不会终止其他项目或原8767本地服务。

停止先撤销所有会话，再终止并等待本次cloudflared子进程，最后退出源站、移除网址/二维码。启动失败或隧道退出也执行清理；若监督程序被系统强制杀死，内存会话和本进程源站随之消失，无法继续生成，极端情况下需在系统活动监视器检查残留cloudflared。自动化不能保证设备断电或操作系统崩溃时优雅关闭。

## 验收与公网核验

- `tests/test_classroom_tunnel.py`：身份/代理/CSRF/数据/限流/会话/错误与导出保护。真实监督程序+Uvicorn+HTTP启停测试使用**明确模拟的cloudflared可执行文件**，不代表建立真实隧道。
- `scripts/verify_classroom_browser.py`：真实Chromium经过本地自签名HTTPS模拟代理，验证登录失败/成功、Secure Cookie、真实Agent调用、搜索/筛选、修改、下载、XSS文本渲染、手机视口、退出撤销。测试证书和私钥仅在临时目录，未提交；浏览器证书例外与无沙箱参数只用于测试，不用于公网核验或正常Mac启动。
- 证据在 `docs/classroom-tunnel-evidence/`。`public_cloudflare_verified=false`是明确结果，不能将这些截图冒充公网访问成功。
- 本地启动真实隧道后，可选运行 `.venv/bin/python scripts/check_classroom_https.py --origin <本次HTTPS网址>`；访问码在交互终端隐藏输入，不在argv/日志。它保持正式TLS验证，拒绝重定向，检验匿名/错误码/CSRF拒绝、正确登录、Cookie、24主题、10/20人动态生成、pilot拒绝和退出撤销。仅当全部检查通过才输出`public_https_verified=true`，不调用付费模型。
- 课堂最终人工验证：手机蜂窝网打开网址；错误码应拒绝；正确码生成MOCK草稿并下载；教师双击停止后，手机刷新/重新生成必须失败。浏览器中已有的MOCK页面或已下载文件不会被远程抹除。

## 官方依据与仍待平台实测

已读取Cloudflare官方GitHub源码（2026-10-30）：

- [quick_tunnel.go](https://github.com/cloudflare/cloudflared/blob/master/cmd/cloudflared/tunnel/quick_tunnel.go)：无账户Quick Tunnel、临时URL及无可用性保证说明。
- [cmd.go](https://github.com/cloudflare/cloudflared/blob/master/cmd/cloudflared/tunnel/cmd.go)：显式`--url`进入Quick Tunnel分支。
- [origin_proxy.go](https://github.com/cloudflare/cloudflared/blob/master/ingress/origin_proxy.go)：Host重写条件及原Host处理。

官方文档入口：[Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)。此文档站在本环境被网络策略阻断，未声称已读取其当前正文。

尚需Mac与校园网络实测：安装的cloudflared版本/系统信任、外连可达性、实际HTTPS代理头、随机域名分配、手机Safari/iPad/其他电脑访问、跨网络生成及停止后失效。公网验证通过前，结论仅为**可审查的课堂演示实现，尚未完成公网交付验收**。
