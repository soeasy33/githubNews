# GitHub 项目速递（本地点击运行）

这是一个在你自己的电脑上运行的小工具。**不会定时运行或自动提醒**：每次点击“现在获取并发送邮件”时，才会获取榜单并发送一封邮件到 `zachary.3302@outlook.com`。

邮件包含：
- GitHub Trending 今日榜 Top 10
- Star 增长 Top 10（与本机上次运行时保存的 Star 快照比较）
- 项目简介的中文翻译

## 安装和运行

需要 Python 3.10 或更新版本。克隆仓库后，在仓库目录打开终端：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python github_news_app.py
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python github_news_app.py
```

首次启动会打开小窗口。首次点击只建立本机 Star 基准并发送榜单；之后每次点击会将当前 Star 数与上次运行保存的快照比较。请保留 `data/star_history.json`，否则会重新建立基准。增长榜只统计程序采集到的候选项目，不是对 GitHub 全站每个仓库的完整扫描。

## 邮件配置

编辑 `.env`：

```dotenv
MAIL_FROM=你的Outlook发件邮箱
MAIL_PASSWORD=你的Outlook应用密码
GITHUB_TOKEN=
```

- `MAIL_FROM` 是你用来发信的 Outlook 邮箱，不是收件人。
- `MAIL_PASSWORD` 使用 Outlook/Microsoft 允许 SMTP 登录的密码或应用密码。不要把密码提交到 GitHub。
- `GITHUB_TOKEN` 可选；填入个人访问令牌可提高 GitHub API 限额。只需公开仓库读取权限。
- 收件地址固定为 `zachary.3302@outlook.com`。

如果 Outlook 拒绝 SMTP 登录，需在 Microsoft 账户中确认 SMTP AUTH/应用密码是否可用；账号安全策略可能不允许传统 SMTP 密码登录。

## 启动方式

之后直接在仓库目录运行 `python github_news_app.py`，点击按钮才会抓取并发送邮件。不会创建定时任务或 GitHub Actions。
