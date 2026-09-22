# AI 平台每日自动签到（Docker 版）

每天定时为 **WPS灵犀 / MiniMax Code / 百度搭子 / Qoder / 魔搭** 自动签到，
结果通过企业微信群机器人卡片推送。适配器架构：**新增一个平台 = 在 `app/platforms/`
加一个文件 + 注册表 import 一行**。

## 功能特性

- **幂等**：某平台当天成功（或已签）后永不再发请求，容器重启/补跑安全。
- **重试**：失败/服务器拥挤按 `RETRY_TIMES` 指数退避重试（10s/20s/40s）；
  凭证失效（auth 类）不重试，直接告警。
- **请求日志**：每次尝试追加 `data/logs/requests.log`（JSON 行）。
- **通知**：企微 **textcard**（大标题"签到成功 n/n"+每平台一行色圆点明细，
  奖励/余X/连N天，失败红色+原因）。微信插件兼容铁律：markdown 与 template_card
  在微信端显示"暂不支持"，均已弃用；textcard 被拒时兜底纯文本。
  双通道：**群机器人 Webhook**（`WECOM_WEBHOOK`）或**自建应用**
  （`WECOM_CORP_ID/SECRET/AGENT_ID` + `WECOM_TO_USER`/`WECOM_CHAT_ID`，可配
  `WECOM_API_BASE` 反代解决动态 IP/可信 IP，access_token 自动缓存与失效刷新；
  应用通道配置齐全时优先）。
- **网页面板**：`web` 子命令，仪表盘（进度条+每平台卡片+一键签到）与
  `/settings`（分字段凭证粘贴导入、网页登录、扫描本机账号、清空凭证）。
- **保活**：每轮签到后对各平台发轻量已认证请求续会话，面板显示保活日期。
- **补跑**：当天有 busy/error 平台时 daemon 每 30 分钟补跑一轮（最多 6 轮），
  全部完成即止。
- **推送去重**：daemon 只在"结果签名变化"时发卡（首轮必发、有平台状态变化才再发、
  全成功终态必发），失败日不再每 30 分钟刷屏；CLI `run-once` 手动跑必发。
- **凭证过期检测**：JWT 类（Qoder/MiniMax）按 exp 精确判定；Cookie 类按导入时间估算 30 天临期提醒。

## 快速开始（飞牛 NAS / 任意 Docker 主机）

```bash
git clone <本仓库> ai-checkin && cd ai-checkin
cp .env.example .env        # 填 WECOM_WEBHOOK 等
docker compose up -d --build
docker compose exec ai-checkin python -m app.main status   # 五平台凭证与今日状态
# 浏览器打开 http://NAS_IP:8000 查看网页面板（web 容器）
```

## 凭证获取（两条路径）

| 平台 | 路径 A：浏览器登录（推荐） | 路径 B：手动/客户端提取 |
|------|--------------------------|------------------------|
| WPS 灵犀 | `docker compose exec ai-checkin python -m app.main login wps`（无头刷新）；首次扫码在 PC 端 `python -m app.main login wps --headful` | F12 复制 `lingxi.kdocs.cn` 请求 Cookie 整串 |
| 百度搭子 | 同上 `login dazi` | 登录 `console.bce.baidu.com` F12 复制 Cookie（需含 `bce-user-info`） |
| MiniMax | 同上 `login minimax`（自动抓 Cookie+localStorage token） | F12 复制任意请求头 `token`（JWT） |
| 魔搭 | 同上 `login modelscope`；或 PC 端 `python tools/win_client_extract.py` 从 `~/.wb-switch/modelscope_login.json` 提取 | SDK 令牌（ms- 开头）在魔搭个人中心复制 |
| Qoder | 不支持网页登录 | 抓包 `openapi.qoder.com.cn` 任意请求，复制 `Authorization: Bearer` 后的串（约 10 天由客户端轮换，过期重贴） |

**inbox 信箱机制**：任何来源的凭证写成 `data/inbox/<platform>.json`
（内容 `{"cookie": "..."}` 或 `{"token": "..."}`，魔搭两者都要），
每轮任务前自动导入（**增量合并**：只更新贴过的字段，其余保留）并改名为 `.imported`。
`scan` 子命令/面板按钮可自动扫描本机 `~/.wb-switch/` 已捕获凭证。
PC 端跑 `login --headful` 后可把 `inbox/` 拷到 NAS 共享目录挂载的 `data/inbox/`。

## 环境变量（.env）

见 [.env.example](.env.example)。核心：`CHECKIN_TIME`（默认 10:05，
Qoder 活动 10:00 开放）、`RETRY_TIMES`、`WECOM_WEBHOOK`。
代码与镜像不含任何真实密钥/Webhook。

## 持久化目录（挂载 `./data:/data`）

```
data/
├── inbox/          # 凭证信箱（投放口）
├── credentials/    # 已导入凭证（明文 JSON，目录权限保持 700）
├── browser/        # Playwright storage_state + 登录卡点截图
├── logs/           # requests.log 请求日志
├── state.json      # 每日签到状态（幂等依据，跨进程文件锁）
└── last_run.txt    # 守护模式标记：'日期 done' 或 '日期 <轮次> <HH:MM>'
```

## 开发 / 测试

```bash
pip install -r requirements-dev.txt
python -m pytest            # 159 项，全离线（本地回环假服务器 + 真实报文黄金样本）
```

## 部署注意

- **网页面板无鉴权**且可写（触发签到/改凭证），**只可暴露内网**，勿做端口映射到公网。
- bind mount 的 `./data` 属主需与容器用户一致：NAS 上先 `sudo chown -R 1000:1000 data`。
- 容器内 Chromium 以 `--no-sandbox` 启动（镜像无 user-namespace，内网可接受）。

## 已知限制

- **魔搭**：无 claim 接口，+250 魔粒/日由服务端按"登录日首访"判定。
  当前用 `earn/rules` 复查判定 + HTTP 首访触发；**纯 HTTP 触发能否首访发放待
  归因冒烟**（部署次日 00:00-00:10 跑 `run-once modelscope` 验证 transactions；
  测前停掉本机其它带 30 分钟 keepalive 的旧签到进程防抢发）。失败则把
  `trigger_visit` 升级为 Playwright 浏览器访问（镜像已内置）。
- **Qoder**：只走 campaigns 权威通道；legacy `daily-check-in/claim` 恒返 409，
  绝不请求、绝不当作"已签到"。
- 多账号轮转 = 二期（现有 state/凭证结构已按平台分文件，预留扩展位）。
- 仅自用内网部署；凭证明文存储于挂载卷，注意目录权限。
