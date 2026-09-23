# Changelog

遵循语义化版本（SemVer）。版本号单一来源：`app/__init__.py` 的 `__version__`；
发版流程 = 改版本号 + 更新本文件 + `git tag vX.Y.Z` + push main 与 tags。

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
