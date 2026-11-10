#!/usr/bin/env python3
"""A click-to-run local GitHub Trending and star-growth email app."""

from __future__ import annotations

import html
import json
import os
import smtplib
import threading
import tkinter as tk
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "star_history.json"
RECIPIENT = "zachary.3302@outlook.com"
USER_AGENT = "githubNews-local-app/1.0 (personal use)"

load_dotenv(ROOT / ".env")


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_trending() -> list[dict]:
    response = requests.get(
        "https://github.com/trending?since=daily",
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    projects = []
    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a")
        if not link:
            continue
        repo = link.get("href", "").strip("/")
        if repo.count("/") != 1:
            continue
        description = article.select_one("p")
        projects.append({
            "repo": repo,
            "description": description.get_text(" ", strip=True) if description else "",
        })
        if len(projects) == 25:
            break
    return projects


def get_recent_starred_repositories() -> list[dict]:
    # This is a practical candidate pool, not a complete scan of all GitHub repos.
    since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    response = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": f"created:>={since}", "sort": "stars", "order": "desc", "per_page": 100},
        headers=github_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("items", [])


def get_repo_details(repo: str) -> dict:
    response = requests.get(f"https://api.github.com/repos/{repo}", headers=github_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def translate_to_chinese(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "暂无项目简介"
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text[:4500]},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        parts = response.json()[0]
        translated = "".join(part[0] for part in parts if part and part[0])
        return translated or text
    except (requests.RequestException, ValueError, TypeError, IndexError):
        # Keep the original description rather than failing the whole report.
        return f"（中文翻译暂不可用）{text}"


def load_history() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_history(projects: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "stars": {p["repo"]: p["stars"] for p in projects},
    }
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_report(status_callback) -> tuple[list[dict], list[dict], str]:
    previous = load_history()
    previous_stars = previous.get("stars", {})
    first_run = not bool(previous_stars)
    status_callback("正在读取 GitHub Trending…")
    trending = get_trending()

    status_callback("正在查找近 30 天创建、Star 较多的项目…")
    search_results = get_recent_starred_repositories()
    projects_by_name = {}
    for item in search_results:
        projects_by_name[item["full_name"]] = item

    # Include current Trending projects in the star-growth candidate set as well.
    for item in trending:
        repo = item["repo"]
        if repo not in projects_by_name:
            try:
                projects_by_name[repo] = get_repo_details(repo)
            except requests.RequestException:
                continue

    projects = []
    for item in projects_by_name.values():
        name = item.get("full_name") or item.get("repo")
        if not name:
            continue
        description = item.get("description") or next(
            (t["description"] for t in trending if t["repo"] == name), ""
        )
        old_stars = previous_stars.get(name)
        stars = int(item.get("stargazers_count", 0))
        projects.append({
            "repo": name,
            "url": item.get("html_url") or f"https://github.com/{name}",
            "stars": stars,
            "growth": max(0, stars - old_stars) if isinstance(old_stars, int) else 0,
            "language": item.get("language") or "未注明",
            "description": description or "暂无项目简介",
        })

    if not projects:
        raise RuntimeError("没有获取到项目数据，请稍后重试。")

    # The first click establishes a baseline; growth becomes meaningful from the next run.
    save_history(projects)
    growth_top = sorted(projects, key=lambda p: p["growth"], reverse=True)[:10]

    details = {p["repo"]: p for p in projects}
    trending_top = []
    for item in trending[:10]:
        project = details.get(item["repo"])
        if project:
            trending_top.append(project)
        else:
            trending_top.append({
                "repo": item["repo"], "url": f"https://github.com/{item['repo']}",
                "stars": 0, "growth": 0, "language": "未注明",
                "description": item["description"] or "暂无项目简介",
            })

    status_callback("正在翻译项目介绍…")
    translated_cache = {}
    for project in growth_top + trending_top:
        source = project["description"]
        if source not in translated_cache:
            translated_cache[source] = translate_to_chinese(source)
        project["description_zh"] = translated_cache[source]

    snapshot_time = previous.get("saved_at")
    interval = f"与上次运行比较（上次：{snapshot_time}）" if snapshot_time else "首次运行：已建立基准；再次运行后显示 Star 增长"
    return growth_top, trending_top, interval


def render_section(title: str, projects: list[dict], show_growth: bool) -> str:
    rows = []
    for index, project in enumerate(projects, 1):
        repo = html.escape(project["repo"])
        url = html.escape(project["url"], quote=True)
        desc = html.escape(project.get("description_zh", ""))
        language = html.escape(project["language"])
        stars = f"{project['stars']:,}"
        growth = f"+{project['growth']:,}" if show_growth else "—"
        rows.append(
            "<tr>"
            f"<td>{index}</td><td><a href=\"{url}\">{repo}</a></td>"
            f"<td>{language}</td><td>{stars}</td><td>{growth}</td><td>{desc}</td>"
            "</tr>"
        )
    return (
        f"<h2>{html.escape(title)}</h2>"
        "<table border='1' cellpadding='7' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        "<tr><th>#</th><th>项目</th><th>语言</th><th>Stars</th><th>新增 Stars</th><th>中文介绍</th></tr>"
        + "".join(rows) + "</table>"
    )


def make_email(growth_top: list[dict], trending_top: list[dict], interval: str) -> EmailMessage:
    sender = os.getenv("MAIL_FROM", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip()
    if not sender or not password:
        raise RuntimeError("请先在 .env 中设置 MAIL_FROM 和 MAIL_PASSWORD。")
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    content = (
        "<!doctype html><html><body style='font-family:Arial,sans-serif;color:#222'>"
        f"<h1>GitHub 每日项目速递</h1><p>生成时间：{html.escape(now)}</p>"
        f"<p>{html.escape(interval)}</p>"
        + render_section("Star 增长榜 Top 10", growth_top, True)
        + render_section("GitHub Trending Top 10", trending_top, False)
        + "<p style='color:#666'>Star 增长榜按本机上次运行时保存的快照计算；仅覆盖本次采集到的候选项目。</p>"
        "</body></html>"
    )
    message = EmailMessage()
    message["Subject"] = f"GitHub 项目速递 - {datetime.now().astimezone().strftime('%Y-%m-%d')}"
    message["From"] = sender
    message["To"] = RECIPIENT
    message.set_content("你的邮件客户端不支持 HTML，请使用 HTML 模式查看 GitHub 项目速递。")
    message.add_alternative(content, subtype="html")
    return message


def send_report(status_callback) -> None:
    growth_top, trending_top, interval = collect_report(status_callback)
    status_callback("正在发送邮件到 " + RECIPIENT + "…")
    sender = os.getenv("MAIL_FROM", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip()
    if not sender or not password:
        raise RuntimeError("请先在 .env 中设置 MAIL_FROM 和 MAIL_PASSWORD。")
    message = make_email(growth_top, trending_top, interval)
    with smtplib.SMTP("smtp-mail.outlook.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)


class GitHubNewsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("GitHub 项目速递")
        root.geometry("480x220")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="GitHub 项目速递", font=("Segoe UI", 17, "bold")).pack(pady=(4, 8))
        ttk.Label(
            frame,
            text="点击按钮后抓取 Star 增长榜和 Trending 榜，并发送到\n" + RECIPIENT,
            justify="center",
        ).pack(pady=5)
        self.status = tk.StringVar(value="就绪。程序不会自动发送邮件。")
        ttk.Label(frame, textvariable=self.status, wraplength=430, justify="center").pack(pady=10)
        self.button = ttk.Button(frame, text="现在获取并发送邮件", command=self.on_click)
        self.button.pack(pady=4, ipadx=12, ipady=5)

    def on_click(self):
        self.button.configure(state="disabled")
        self.status.set("准备开始…")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            send_report(lambda text: self.root.after(0, self.status.set, text))
            self.root.after(0, self.status.set, "发送成功！请检查 Outlook 收件箱或垃圾邮件文件夹。")
            self.root.after(0, lambda: messagebox.showinfo("完成", f"日报已发送到 {RECIPIENT}"))
        except Exception as exc:
            self.root.after(0, self.status.set, "运行失败，请检查网络和 .env 配置。")
            self.root.after(0, lambda: messagebox.showerror("发送失败", str(exc)))
        finally:
            self.root.after(0, lambda: self.button.configure(state="normal"))


def main():
    root = tk.Tk()
    GitHubNewsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
