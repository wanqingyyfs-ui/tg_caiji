# TG 采集器

`tg_caiji` 是 `tg_suoyin` 的配套采集项目。

它使用 Telegram 用户号通过 Telethon 监听你指定的群组/频道，从消息中发现公开 `t.me/username` 或 `@username` 资源链接，保存到本地 SQLite，然后通过 Web 审核面板筛选、审核、导出为 `tg_suoyin` 可直接导入的 JSONL 文件。

## 项目定位

本项目只负责：

- 监听指定 Telegram 群组/频道
- 从消息中提取公开 Telegram 频道、群组、机器人链接
- 初步去重、初步识别类型、补充元信息
- 提供后台面板审核资源
- 导出 `tg_suoyin_links.jsonl`

本项目不负责：

- 不直接修改 `tg_suoyin` 前端
- 不直接生成 `web/public/data.json`
- 不绕过 `tg_suoyin` 现有过滤、分类、导出流程
- 不采集私聊
- 默认不导出私密邀请链接

推荐数据链路：

```text
tg_caiji
    ↓ exports/tg_suoyin_links.jsonl
tg_suoyin/scripts/import_collected_links.py
    ↓ data/rectg.db links 表
tg_suoyin/scripts/crawl.py --new
    ↓ entries 表
tg_suoyin/scripts/rebuild_index.py
    ↓ web/public/data.json
```

## 技术栈

- Python 3.11+
- Telethon
- FastAPI
- Jinja2
- SQLite
- PyYAML
- python-dotenv

## 安装

```powershell
cd D:\编程
git clone https://github.com/wanqingyyfs-ui/tg_caiji.git
cd tg_caiji

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`：

```env
TG_API_ID=你的_api_id
TG_API_HASH=你的_api_hash
TG_SESSION_NAME=collector
COLLECTOR_DB=data/collector.db
EXPORT_PATH=exports/tg_suoyin_links.jsonl
ADMIN_HOST=127.0.0.1
ADMIN_PORT=8008
MIN_EXPORT_CONFIDENCE=0.6
AUTO_ENRICH_ON_DISCOVERY=false
REQUEST_DELAY_SECONDS=2.0
```

## 初始化数据库

```powershell
python -m collector.main init-db
```

## 登录 Telegram 用户号

```powershell
python -m collector.main login
```

第一次会提示输入手机号、验证码、二步验证密码。登录 session 默认保存到：

```text
data/sessions/collector.session
```

这个文件不要上传 GitHub。

## 添加监听源

方式一：通过后台面板添加。

```powershell
python -m collector.main web
```

打开：

```text
http://127.0.0.1:8008
```

进入「监听源」页面，添加群组/频道。

方式二：命令行添加：

```powershell
python -m collector.main add-source --name "中文资源群A" --chat "@example_group" --limit 500
```

方式三：从配置文件导入：

```powershell
copy config\sources.example.yaml config\sources.yaml
python -m collector.main import-sources --file config/sources.yaml
```

## 诊断监听源

添加监听源后，先运行：

```powershell
python -m collector.main doctor --limit 30
```

它会检查：

- 监听源是否启用
- 当前 Telegram 用户号是否能访问该群/频道
- 最近消息是否能读取
- 最近消息里是否有可采集的 `t.me/username` 或 `@username`

如果这里显示候选链接为 0，说明最近抽样消息里没有公开资源链接，或者来源写错、用户号没权限访问。

## 回补历史消息

```powershell
python -m collector.main backfill --limit 500
```

默认会识别 `t.me/username` 和 `@username`。如果只想识别完整链接，不识别 `@username`：

```powershell
python -m collector.main backfill --limit 500 --no-mentions
```

## 实时监听

推荐命令：

```powershell
python -m collector.main listen --backfill-on-start --backfill-limit 200 --debug
```

说明：

- `listen` 只监听未来新消息。
- `--backfill-on-start` 会在监听前先回补一批历史消息，避免刚启动时面板为空。
- `--debug` 会打印每条收到的消息，即使没有链接也会显示，方便判断到底有没有监听到消息。
- 默认识别 `@username`；如果不想识别，添加 `--no-mentions`。

普通后台监听：

```powershell
python -m collector.main listen
```

## 补充资源元信息

```powershell
python -m collector.main enrich --limit 100
```

这会用 Telegram API 尝试解析候选链接的标题、简介、人数、类型等。注意不要频繁运行，过快解析 username 容易触发 Telegram flood wait。

## 审核面板

启动：

```powershell
python -m collector.main web
```

打开：

```text
http://127.0.0.1:8008
```

面板支持：

- 查看总发现数、新资源数、已通过数、已拒绝数
- 添加/启用/停用监听源
- 按状态筛选
- 按类型筛选
- 按最小人数筛选
- 按最大人数筛选
- 按标题、用户名、简介关键词搜索
- 单条审核通过/拒绝
- 批量通过/拒绝
- 导出已通过资源

## 导出给 tg_suoyin

```powershell
python -m collector.main export --status approved --output exports/tg_suoyin_links.jsonl
```

导出格式为 JSONL，每行一条：

```json
{"url":"https://t.me/example","username":"example","name":"示例频道","type_hint":"channel","source_chat":"中文资源群A","source_message_id":123,"discovered_at":"2026-06-13T13:30:00+07:00","confidence":0.9}
```

## 导入 tg_suoyin

在 `tg_suoyin` 项目中运行：

```powershell
cd D:\编程\tg_suoyin

python scripts/import_collected_links.py --file D:\编程\tg_caiji\exports\tg_suoyin_links.jsonl

python scripts/crawl.py --new

npm run rebuild

npm run build
```

## 质量和安全原则

默认拒绝导出以下链接：

- `t.me/+xxxx`
- `t.me/joinchat/xxxx`
- `t.me/c/...`
- `t.me/share/url`
- `t.me/addstickers`
- `t.me/proxy`
- 没有公开 username 的链接

默认不采集普通用户个人资料，不保存手机号，不监听私聊，不导出私密邀请链接。

## 常用命令

```powershell
python -m collector.main init-db
python -m collector.main login
python -m collector.main add-source --name "资源群" --chat "@example_group"
python -m collector.main doctor --limit 30
python -m collector.main backfill --limit 500
python -m collector.main listen --backfill-on-start --backfill-limit 200 --debug
python -m collector.main enrich --limit 100
python -m collector.main web
python -m collector.main export --status approved
python -m unittest
```
