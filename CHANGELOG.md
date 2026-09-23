# Changelog

遵循语义化版本（SemVer）。版本号单一来源：`app/__init__.py` 的 `__version__`；
发版流程 = 改版本号 + 更新本文件 + `git tag vX.Y.Z` + push main 与 tags。

## v1.4.4 — 2026-09-23

### 优化：通知定稿两行版式
- 行1 `🔸 平台 +积分`（精简去"积分"字样），行2 全角空格缩进
  `100·09-30到期｜余2592｜连3天`（无附加信息不出第二行）。
- 超 500 字节改为按平台整块（两行）从尾部删。

## v1.4.3 — 2026-09-23

### 新功能
- 通知行追加"最快到期积分"：签到轮逐账号算 expiring（同面板缓存，
  set_expiring 落 state），多账号聚合取日期最早；textcard 行格式
  `🔸 平台 +100｜100 · 09-30到期｜余2592｜连3天`。
- CheckinResult 新增 expiring 字段；取最早逻辑收敛为 scheduler.earliest_of
  （webapp 复用，删重复）。

## v1.4.2 — 2026-09-23

### 优化
- 通知行首图标定稿（用户选 A 款改橙）：全平台统一 🔸 小橙菱，
  失败统一 🔻 红色警示；不再按平台分色。

## v1.4.1 — 2026-09-23

### 优化
- 通知行首图标全部改菱形：wps◆ dazi🔷 minimax💠 qoder🔶 魔搭❖ linkai◇
  workbuddy🔹 trae🔸（emoji 无红/紫/绿菱形，取近色或单色，互不重复）；
  失败标记 🔴→🔻 保持红色警示。

## v1.4.0 — 2026-09-23

### 优化：设置页重做
- 主页设置入口改为头部 ⚙️ 齿轮按钮（原文字链接移除）。
- 移除「扫描本机账号导入」与「网页登录获取」按钮及 /api/scan、/api/login
  路由（PC 端 inbox 投递与 CLI login 子命令不受影响）。
- 账号管理改版：每账号一行（备注名+凭证状态注记"有效至…/存于…"），
  「更新凭证」按需展开表单（不再回显凭证）；「+ 添加账号」展开独立
  新账号表单；删除改小号按钮。
- 视觉与主页统一：平台色图标、卡片圆角、同一按钮/胶囊体系。

## v1.3.0 — 2026-09-23

### 新功能：每平台多账号（全账号签到 + 卡片聚合）
- 凭证仓库升级为账号列表（`{"accounts":[{…,"id"}]}`），旧单账号文件/旧
  state 记录自动兼容（id=main 沿用原键，零迁移）；inbox 导入=本机账号
  轮换合并，设置页=按行显式增删改。
- 调度：每平台逐账号签到，各自落记录（`platform#id`）；余额/保活/明细
  缓存逐账号刷新；单账号行为与旧版逐字节一致。
- 面板：卡片聚合今日已得/余额合计、最快到期跨账号取最早、胶囊"·N号"；
  明细弹窗按账号分组；设置页每账号一行（备注改名/保存/删除/+添加账号）。
- 通知：聚合行显示合计；某账号失败时点名"小号：原因"。
- 安全（评审修复）：账号 id 白名单 `[A-Za-z0-9_-]{1,16}`、label 去引号
  尖括号+限长、设置页渲染 html.escape、凭证写加跨进程锁、已删账号的
  幽灵记录不再钉死卡片状态。

## v1.2.4 — 2026-09-23

### 修复
- WorkBuddy 明细包名与官方页不符：官方客户端不用后端 PackageName（运营
  原文），按商品码映射前端文案。照抄 wb-switch credit-package-names.ts
  码表（平台奖励积分/版本基础用量/购买积分…），未登记码回落 PackageName。

## v1.2.3 — 2026-09-23

### 新功能
- 面板卡片新增"最快到期"行：余额循环（默认每小时）顺带调各平台明细接口，
  取最快过期的一笔积分缓存进 state（`set_expiring` 只合并该字段），
  显示如"100 · 10-01到期"；无明细接口平台显示 —。

## v1.2.2 — 2026-09-23

### 修复
- WorkBuddy 积分明细补上失效时间：改查官方
  `get-user-resource-paid/free-packages` 两接口的逐包 `data.Accounts`
  （含 PackageName/DeductionEndTime，码表与长期占位解析移植自 wb-switch
  credits.rs），summary 接口继续只用于余额合计。

## v1.2.1 — 2026-09-23

### 优化
- 积分明细弹窗：TraeWork 按官方口径区分积分池（product_id 209=Work，
  其余=通用；实测通用2950/Work2500 与官网明细吻合），多池时头部显示小计卡。
- 明细行改固定列栅格（标签/名称/金额/失效时间跨行对齐）。
- WorkBuddy 标签统一为"资源包"，合并包数移入名称。

## v1.2.0 — 2026-09-23

### 新功能
- 点击卡片弹出「积分明细」窗（浅色控制台风格）：逐包列名称/额度/失效时间。
  - TraeWork：entitlement 包列表（组名+描述+N天后过期，过期剔除、失效升序）
  - MiniMax：credit/details 逐包余量+expire_at_ms
  - WorkBuddy：资源包余量明细（官方 summary 无失效时间，显示占位）
  - 其余平台：弹窗提示"官方接口不提供积分流水明细"
- 新增 `Adapter.breakdown()` 钩子与 `GET /api/detail/<platform>` 接口。

## v1.1.3 — 2026-09-23

### 优化
- 面板卡片"上次签到"与"上次执行"合并为一条：显示最近一次成功签到的
  日期+时刻（当天完成则显示「今天 HH:MM:SS」），失败时刻仍由
  状态胶囊与"失败原因"行表达。

## v1.1.2 — 2026-09-23

### 修复
- TraeWork/MiniMax/WorkBuddy 的"今日已签到(already)"分支未填 reward 字段，
  面板/卡片"今日已得"显示为空。现在从状态接口取今日所得回填
  （Trae=credits、MiniMax=今日 points、WorkBuddy=today_credit）。

## v1.1.1 — 2026-09-23

### 修复
- WorkBuddy 余额：原读活动接口 total_credits（=活动累计 800，非余额）。
  改为 www.workbuddy.cn `get-user-resource-summary` 各包 CycleRemainCapacity
  之和（实测 5026.24 与官网一致，支持小数）。
- TraeWork 余额：原读签到 status.credits（=今日所得 150）。改为
  `user_current_entitlement_list` usage_summary total−consumed
  （实测 5450 = 通用 2950 + Work 2500）。

## v1.1.0 — 2026-09-23

### 新增
- **WorkBuddy 平台**（腾讯 copilot.tencent.com，每日签到积分）：桌面端会话
  `workbuddy-desktop.info` 扫描导入；协议与幂等契约（null/10001=已签）逆向自
  GitHub `Minatoxiaohu/agent-auto-signin`，本机实测。卡片圆点 🔹。
- **TraeWork 平台**（api.trae.cn，每日 200 积分）：桌面端 storage.json 登录态
  经 wb-switch 捕获扫描导入，Cloud-IDE-JWT 直调 status/claim；claim 9004 按
  "已领"幂等处理。卡片圆点 🔸。
- 扫描器：`agent_accounts.json` 支持 trae（含 device_id），新增
  `%LOCALAPPDATA%\CodeBuddyExtension\...\workbuddy-desktop.info` 来源。

## v1.0.1 — 2026-09-23

面板数据正确性修复（用户截图审查发现）。

### 修复
- **余额刷新伪造签到状态**：`_write_balance` 对无状态记录默认 `state:'ok'`，
  把 LinkAI 一整天的 870 真拒签掩盖成"已签到"并导致当天跳过重试。
  现改为 `DailyState.set_balance()` 只合并 balance 字段，绝不触碰 state/at。
- **「上次执行」被余额刷新污染**：余额回写不再更新 `at`，该字段恢复"最近一次
  签到执行"语义。
- **失败状态从不落盘**：run_all 现把 error/busy 也写入 state.json，
  面板卡片新增「失败原因」行（busy 为「说明」），失败不再只在日志里。
- **余额循环补打保活标记**：credits 成功即 touch_keepalive（兑现"兼作保活"），
  修复搭子保活恒"—"。
- MiniMax credits 字段映射（remaining_amount/expire_at_ms + 无 data 包裹响应）。
- 搭子余额改读顶层 `totalPoints - usedPoints`（subscription 常为空）。

## v1.0.0 — 2026-09-23

首个正式版本，NAS 生产环境已运行。

### 新增
- 六平台每日自动签到适配器：WPS灵犀 / MiniMax Code / 百度搭子 / Qoder / 魔搭 / LinkAI
- 幂等调度 daemon：当天成功即停；busy/error 每 30 分钟补跑（最多 6 轮，指数退避重试）
- 企业微信自建应用通知（textcard，状态签名变化才推送）+ 群机器人 Webhook 双通道
- 网页「签到中心」面板（进度条/明细卡/一键签到）+ 设置页（凭证导入/网页登录获取/扫描本机账号/保活）
- 凭证体系：inbox 信箱增量导入、JWT 过期精确检测、Cookie 临期提醒
- Docker 部署：Playwright 基座镜像（容器内无头/有头登录）、compose 双服务（daemon + web）
- 版本管理：`python -m app.main version`、面板页脚展示 `vX.Y.Z`

### 已知限制
- 多账号轮转为二期规划
- 魔搭无 claim 接口，依赖 HTTP 首访触发 + rules 复查判定
