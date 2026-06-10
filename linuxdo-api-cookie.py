#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron: 0 */6 * * *
new Env("Linux.Do 快速升级")

Linux.Do 快速升级脚本 - 纯 API 版本（Cookie 鉴权，无需 Chrome）
版本: 4.1.3 (跳过 current.json 限速端点)
"""

import os
import time
import random
import re
import traceback
import functools
import json
from loguru import logger
from curl_cffi import requests
from tabulate import tabulate

HOME_URL = "https://linux.do"
CSRF_URL = "https://linux.do/session/csrf"

USERNAME = os.environ.get("LINUXDO_USERNAME") or os.environ.get("USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD") or os.environ.get("PASSWORD")
BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in ["false", "0", "off"]

LINUXDO_COOKIE_T = os.environ.get("LINUXDO_COOKIE_T", "").strip()

GOTIFY_URL = os.environ.get("GOTIFY_URL")
GOTIFY_TOKEN = os.environ.get("GOTIFY_TOKEN")
SC3_PUSH_KEY = os.environ.get("SC3_PUSH_KEY")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
WECHAT_API_URL = os.environ.get("WECHAT_API_URL")
WECHAT_AUTH_TOKEN = os.environ.get("WECHAT_AUTH_TOKEN")

LINUXDO_PROXY = os.environ.get("LINUXDO_PROXY") or os.environ.get("HTTP_PROXY")

if LINUXDO_PROXY:
    logger.info(f"已启用代理配置: {LINUXDO_PROXY}")

UPGRADE_CONFIG = {
    "topics_to_browse": 15,
    "likes_to_give": 5,
    "replies_to_post": 2,
}

REPLY_TEMPLATES = [
    "感谢分享！很努力的在向大佬学习了",
    "感谢大佬分享，每天学习一点点",
    "学习了，很有帮助，感谢大佬的无私奉献",
    "支持一下，期待大佬更多的优秀文章",
    "不错的内容哈哈，认真看完了受益匪浅",
    "mark一下，这篇帖子干货满满，得收藏细看",
    "收藏了，每天在论坛看看大佬们的帖子就是爽",
    "有用的信息，希望大家都能多多分享",
    "感谢楼主，一直在找相关的资料，太及时了",
    "不错值得学习。。。先点赞后看养成好习惯",
    "谢谢。加油,看好你。努力向高段位看齐",
    "已查阅感谢分享。非常实用的教程",
    "膜拜大佬，希望以后也能写出这么好的文章"
]


def retry_decorator(retries=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"函数 {func.__name__} 最终执行失败: {str(e)}")
                        raise
                    logger.warning(f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


class LinuxDoUpgrade:
    def __init__(self):
        self.csrf_token = None
        self.current_user = None

        self.session = requests.Session()
        self.proxies = {"http": LINUXDO_PROXY, "https": LINUXDO_PROXY} if LINUXDO_PROXY else None
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": HOME_URL,
        })
        if self.proxies:
            self.session.proxies = self.proxies

        self.stats = {
            'topics_browsed': 0,
            'posts_read': 0,
            'likes_given': 0,
            'replies_posted': 0,
        }

    def refresh_csrf(self) -> str:
        try:
            r = self.session.get(CSRF_URL, impersonate="chrome136")
            if r.status_code == 429:
                logger.warning("CSRF 请求被限速 (429)")
                return None
            if r.status_code != 200:
                logger.warning(f"获取 CSRF 返回: HTTP {r.status_code}")
                return None
            j = r.json() or {}
            self.csrf_token = j.get("csrf")
            if self.csrf_token:
                self.session.headers["X-CSRF-Token"] = self.csrf_token
            return self.csrf_token
        except Exception as e:
            logger.warning(f"获取 CSRF 失败: {e}")
            return None

    def login(self) -> bool:
        logger.info("Linux.Do: 开始登录...")
        if LINUXDO_COOKIE_T:
            return self._login_by_cookie()
        else:
            logger.error(
                "请设置环境变量 LINUXDO_COOKIE_T\n"
                "获取方法:\n"
                "  1. 浏览器登录 https://linux.do\n"
                "  2. F12 → Application → Cookies → linux.do\n"
                "  3. 复制 _t 的 Value（不要解码）\n"
                "  4. 青龙 → 环境变量 → 新建 LINUXDO_COOKIE_T\n"
                "  有效期约 1 年"
            )
            return False

    def _login_by_cookie(self) -> bool:
        """使用 _t Cookie 登录（跳过 current.json，用主题列表验证）"""
        logger.info("使用 Cookie 鉴权模式...")

        self.session.cookies.set("_t", LINUXDO_COOKIE_T, domain="linux.do")

        # 访问主页获取 Cloudflare cf_clearance cookie
        logger.info("预热: 访问主页获取 Cloudflare 放行...")
        try:
            r = self.session.get(
                HOME_URL,
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                impersonate="chrome136"
            )
            logger.info(f"主页返回: HTTP {r.status_code}, Cookie数: {len(self.session.cookies)}")
        except Exception as e:
            logger.warning(f"访问主页异常(可继续): {e}")
        time.sleep(2)

        # 获取 CSRF Token
        csrf = None
        for attempt in range(3):
            csrf = self.refresh_csrf()
            if csrf:
                break
            wait = 15 * (attempt + 1)
            logger.warning(f"获取 CSRF 失败，等待 {wait} 秒后重试 ({attempt+1}/3)...")
            time.sleep(wait)

        if not csrf:
            logger.error("获取 CSRF 失败")
            return False

        # 用主题列表验证登录（比 /session/current.json 限速更宽松）
        logger.info("验证登录状态...")
        for attempt in range(3):
            try:
                r = self.session.get(f"{HOME_URL}/latest.json", impersonate="chrome136")

                if r.status_code == 429:
                    wait = 30 * (attempt + 1)
                    logger.warning(f"触发限速 (429)，等待 {wait} 秒后重试 ({attempt+1}/3)...")
                    time.sleep(wait)
                    continue

                if r.status_code == 200:
                    data = r.json()
                    topic_list = data.get("topic_list", {}).get("topics", [])

                    if topic_list:
                        self.current_user = USERNAME or "已登录用户"

                        # 尝试获取用户名
                        try:
                            ur = self.session.get(f"{HOME_URL}/my/summary.json", impersonate="chrome136")
                            if ur.status_code == 200:
                                udata = ur.json()
                                uname = None
                                # 尝试多种 JSON 结构
                                if udata.get("user_summary"):
                                    uname = udata["user_summary"].get("user", {}).get("username")
                                if not uname and udata.get("users"):
                                    uname = udata["users"][0].get("username")
                                if uname:
                                    self.current_user = uname
                        except Exception:
                            pass

                        logger.success(f"Linux.Do: Cookie 登录成功 ✅ ({len(topic_list)} 个主题)")
                        logger.info(f"  用户: {self.current_user}")
                        return True
                    else:
                        logger.error("获取到空主题列表，Cookie 可能无效")
                        return False
                else:
                    logger.error(f"验证失败: HTTP {r.status_code}")
                    return False

            except Exception as e:
                logger.error(f"验证登录异常: {e}")
                time.sleep(10)

        logger.error("多次重试后仍无法验证登录")
        return False

    def print_connect_info(self):
        logger.info("获取 Connect 信息...")
        try:
            from bs4 import BeautifulSoup
            headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            r = self.session.get("https://connect.linux.do/", headers=headers, impersonate="chrome136")
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table tr")
            info = []
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 3:
                    project = cells[0].text.strip()
                    current = cells[1].text.strip() or "0"
                    requirement = cells[2].text.strip() or "0"
                    info.append([project, current, requirement])
            if info:
                print("-" * 50)
                print(tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty"))
                print("-" * 50)
        except Exception as e:
            logger.warning(f"获取连接信息失败: {e}")

    def get_latest_topics(self, limit: int = 30) -> list:
        topics = []
        try:
            r = self.session.get(f"{HOME_URL}/latest.json", impersonate="chrome136")
            if r.status_code != 200:
                logger.error(f"获取主题列表失败: HTTP {r.status_code}")
                return []
            data = r.json()
            topic_list = data.get("topic_list", {}).get("topics", [])
            for t in topic_list[:limit]:
                topic_id = t.get("id")
                title = t.get("title", "")
                slug = t.get("slug", "")
                if topic_id and title:
                    topics.append({"id": topic_id, "title": title, "slug": slug})
            logger.info(f"获取到 {len(topics)} 个最新主题")
        except Exception as e:
            logger.error(f"获取主题列表异常: {e}")
        return topics

    @retry_decorator(retries=2, delay=1)
    def read_topic(self, topic: dict) -> dict:
        topic_id = topic["id"]
        slug = topic.get("slug", "")
        r = self.session.get(f"{HOME_URL}/t/{slug}/{topic_id}.json", impersonate="chrome136")
        if r.status_code == 429:
            logger.warning("阅读主题被限速，等待 15 秒...")
            time.sleep(15)
            return {}
        if r.status_code != 200:
            logger.debug(f"阅读主题 {topic_id} 失败: HTTP {r.status_code}")
            return {}
        data = r.json()
        posts = data.get("post_stream", {}).get("posts", [])
        self.stats['topics_browsed'] += 1
        self.stats['posts_read'] += len(posts)
        logger.info(f"📖 阅读主题: {topic['title'][:40]}... ({len(posts)} 楼)")
        self._send_topic_timings(topic_id, posts)
        return data

    def _send_topic_timings(self, topic_id: int, posts: list):
        try:
            self.refresh_csrf()
            timings = {}
            for post in posts[:20]:
                post_number = post.get("post_number", 1)
                timings[str(post_number)] = random.randint(3000, 8000)
            data = {
                "topic_id": topic_id,
                "topic_time": random.randint(15000, 60000),
                "timings": timings,
            }
            r = self.session.post(f"{HOME_URL}/topics/timings", json=data, impersonate="chrome136")
            if r.status_code == 200:
                logger.debug(f"✅ 已记录主题 {topic_id} 的阅读时间 ({len(timings)} 楼)")
            else:
                logger.debug(f"记录阅读时间返回: HTTP {r.status_code}")
        except Exception as e:
            logger.debug(f"发送 timings 失败: {e}")

    def like_post(self, post_id: int) -> bool:
        try:
            self.refresh_csrf()
            data = {"id": post_id, "post_action_type_id": 2, "flag_topic": False}
            r = self.session.post(f"{HOME_URL}/post_actions", json=data, impersonate="chrome136")
            if r.status_code == 200:
                self.stats['likes_given'] += 1
                logger.success(f"👍 点赞帖子 {post_id} 成功 ({self.stats['likes_given']})")
                return True
            elif r.status_code == 429:
                logger.warning("点赞被限速，等待 15 秒...")
                time.sleep(15)
            elif r.status_code == 403:
                logger.debug(f"点赞 {post_id} 被拒绝")
            else:
                logger.debug(f"点赞 {post_id} 返回: HTTP {r.status_code}")
            return False
        except Exception as e:
            logger.debug(f"点赞异常: {e}")
            return False

    def reply_to_topic(self, topic_id: int, topic_title: str = "") -> bool:
        try:
            self.refresh_csrf()
            reply_text = random.choice(REPLY_TEMPLATES)
            data = {
                "topic_id": topic_id,
                "raw": reply_text,
                "unlist_topic": False,
                "category": "",
                "is_warning": False,
                "archetype": "regular",
                "typing_duration_msecs": random.randint(3000, 8000),
                "composer_open_duration_msecs": random.randint(5000, 15000),
            }
            r = self.session.post(f"{HOME_URL}/posts", json=data, impersonate="chrome136")
            if r.status_code == 200:
                self.stats['replies_posted'] += 1
                logger.success(f"💬 回复成功: '{reply_text}' -> {topic_title[:30]}... ({self.stats['replies_posted']})")
                return True
            elif r.status_code == 429:
                logger.warning("回复被限速，等待 30 秒...")
                time.sleep(30)
            else:
                logger.warning(f"回复失败 HTTP {r.status_code}: {(r.text or '')[:200]}")
            return False
        except Exception as e:
            logger.warning(f"回复异常: {e}")
            return False

    def auto_upgrade_tasks(self):
        logger.info(f"\n{'='*50}")
        logger.info("🚀 开始执行升级任务 (纯API模式)")
        logger.info(f"{'='*50}")

        topics = self.get_latest_topics(UPGRADE_CONFIG['topics_to_browse'])
        if not topics:
            logger.warning("未获取到主题，跳过")
            return False

        random.shuffle(topics)

        for i, topic in enumerate(topics, 1):
            try:
                logger.info(f"[{i}/{len(topics)}] 处理主题 #{topic['id']}...")
                topic_data = self.read_topic(topic)
                if not topic_data:
                    continue

                posts = topic_data.get("post_stream", {}).get("posts", [])

                if self.stats['likes_given'] < UPGRADE_CONFIG['likes_to_give'] and posts:
                    likeable = [
                        p for p in posts
                        if p.get("actions_summary") and
                        any(a.get("id") == 2 and a.get("can_act") for a in p.get("actions_summary", []))
                    ]
                    if not likeable:
                        likeable = posts[1:5]
                    for post in random.sample(likeable, min(2, len(likeable))):
                        pid = post.get("id")
                        if pid:
                            self.like_post(pid)
                            time.sleep(random.uniform(1, 2))
                        if self.stats['likes_given'] >= UPGRADE_CONFIG['likes_to_give']:
                            break

                if self.stats['replies_posted'] < UPGRADE_CONFIG['replies_to_post']:
                    if random.random() < 0.3:
                        self.reply_to_topic(topic['id'], topic['title'])

                if i < len(topics):
                    time.sleep(random.uniform(5, 12))

            except Exception as e:
                logger.warning(f"处理主题出错: {e}")
                continue

        return True

    def send_notifications(all_stats: str):
    # 尝试使用青龙自带通知
    try:
        import sys
        if '/ql/scripts' not in sys.path:
            sys.path.append('/ql/scripts')
        if '/ql/data/scripts' not in sys.path:
            sys.path.append('/ql/data/scripts')
        
        from notify import send
        send("Linux.Do 升级任务", all_stats)
        logger.success("✅ 已通过青龙自带 notify.py 发送通知")
    except ImportError:
        logger.info("未找到青龙 notify.py，由于未配置自定义通知，跳过推送。")
    except Exception as e:
        logger.warning(f"⚠️ 青龙通知调用失败: {e}")

    def run(self) -> int:
        try:
            logger.info("==== Linux.Do 快速升级脚本开始 (纯API版 v4.1) ====")

            if not self.login():
                logger.error("Linux.Do: 登录失败 ❌")
                return 1

            self.print_connect_info()

            if BROWSE_ENABLED:
                if not self.auto_upgrade_tasks():
                    logger.warning("升级任务未完成")
            else:
                logger.info("BROWSE_ENABLED=false，跳过升级任务")

            logger.info(f"\n{'='*50}")
            logger.info("📊 今日任务完成统计:")
            logger.info(f"  - 浏览主题: {self.stats['topics_browsed']}")
            logger.info(f"  - 阅读帖子: {self.stats['posts_read']}")
            logger.info(f"  - 给出点赞: {self.stats['likes_given']}")
            logger.info(f"  - 发布回复: {self.stats['replies_posted']}")
            logger.info(f"{'='*50}\n")

            self.send_notifications()
            logger.info("==== Linux.Do 快速升级脚本结束 ====")
            return 0

        except Exception:
            logger.error("Linux.Do: 脚本异常 ❌")
            traceback.print_exc()
            return 9


if __name__ == "__main__":
    if not LINUXDO_COOKIE_T:
        logger.error(
            "请设置环境变量 LINUXDO_COOKIE_T\n"
            "获取: 浏览器登录 linux.do → F12 → Application → Cookies → 复制 _t 值（不解码）"
        )
        raise SystemExit(1)
    app = LinuxDoUpgrade()
    raise SystemExit(app.run())
