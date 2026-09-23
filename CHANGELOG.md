# Changelog

遵循语义化版本（SemVer）。版本号单一来源：`app/__init__.py` 的 `__version__`；
发版流程 = 改版本号 + 更新本文件 + `git tag vX.Y.Z` + push main 与 tags。

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
