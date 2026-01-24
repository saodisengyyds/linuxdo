"""
cron: 0 */6 * * *
new Env("Linux.Do 快速升级")
"""

import os
import random
import time
import functools
import sys
import re
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from curl_cffi import requests
from bs4 import BeautifulSoup


# ================== 升级配置 ==================
UPGRADE_CONFIG = {
    "topics_to_browse": 15,        # 每次浏览话题数（加速升级）
    "likes_to_give": 5,            # 每次点赞数
    "replies_to_post": 2,          # 每次回复数（谨慎设置）
}

# 回复内容池
REPLY_TEMPLATES = [
    "感谢分享！",
    "学习了，很有帮助",
    "支持一下",
    "不错的内容",
    "mark一下",
    "收藏了",
    "有用的信息",
    "感谢楼主",
]


def retry_decorator(retries=3, delay=1):
    """重试装饰器"""
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


os.environ.pop("DISPLAY", None)
os.environ.pop("DYLD_LIBRARY_PATH", None)

USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in ["false", "0", "off"]

if not USERNAME:
    USERNAME = os.environ.get("USERNAME")
if not PASSWORD:
    PASSWORD = os.environ.get("PASSWORD")

GOTIFY_URL = os.environ.get("GOTIFY_URL")
GOTIFY_TOKEN = os.environ.get("GOTIFY_TOKEN")
SC3_PUSH_KEY = os.environ.get("SC3_PUSH_KEY")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")  # Telegram Bot Token
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")  # Telegram Chat ID

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"


class LinuxDoUpgrade:
    def __init__(self) -> None:
        from sys import platform

        if platform == "linux" or platform == "linux2":
            platformIdentifier = "X11; Linux x86_64"
        elif platform == "darwin":
            platformIdentifier = "Macintosh; Intel Mac OS X 10_15_7"
        elif platform == "win32":
            platformIdentifier = "Windows NT 10.0; Win64; x64"

        co = (
            ChromiumOptions()
            .headless(True)
            .incognito(True)
            .set_argument("--no-sandbox")
        )
        co.set_user_agent(
            f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        
        # 统计数据
        self.stats = {
            'topics_browsed': 0,
            'posts_read': 0,
            'likes_given': 0,
            'replies_posted': 0,
        }

    @retry_decorator(retries=2, delay=2)
    def login(self):
        """登录 Linux.Do"""
        logger.info("开始登录")
        
        # Step 1: Get CSRF Token
        logger.info("获取 CSRF token...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        resp_csrf = self.session.get(CSRF_URL, headers=headers, impersonate="chrome136")
        csrf_data = resp_csrf.json()
        csrf_token = csrf_data.get("csrf")
        logger.info(f"CSRF Token obtained: {csrf_token[:10]}...")

        # Step 2: Login
        logger.info("正在登录...")
        headers.update(
            {
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://linux.do",
            }
        )

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        resp_login = self.session.post(
            SESSION_URL, data=data, impersonate="chrome136", headers=headers
        )

        if resp_login.status_code == 200:
            response_json = resp_login.json()
            if response_json.get("error"):
                logger.error(f"登录失败: {response_json.get('error')}")
                return False
            logger.success("登录成功!")
        else:
            logger.error(f"登录失败，状态码: {resp_login.status_code}")
            return False

        self.print_connect_info()

        # Step 3: Sync cookies to DrissionPage
        logger.info("同步 Cookie 到 DrissionPage...")
        cookies_dict = self.session.cookies.get_dict()
        dp_cookies = []
        for name, value in cookies_dict.items():
            dp_cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".linux.do",
                    "path": "/",
                }
            )

        self.page.set.cookies(dp_cookies)
        logger.info("Cookie 设置完成，导航至 linux.do...")
        self.page.get(HOME_URL)
        time.sleep(5)
        
        user_ele = self.page.ele("@id=current-user")
        if not user_ele:
            if "avatar" in self.page.html:
                logger.success("登录验证成功 (通过 avatar)")
                return True
            logger.error("登录验证失败")
            return False
        else:
            logger.success("登录验证成功")
            return True
    
    def wait_for_page_load(self, timeout: int = 10):
        """等待页面加载完成"""
        try:
            for i in range(timeout):
                # 检查页面是否加载完成
                ready_state = self.page.run_js("return document.readyState")
                if ready_state == "complete":
                    logger.debug(f"页面加载完成 (耗时 {i}秒)")
                    return True
                time.sleep(1)
            logger.warning(f"等待 {timeout}秒后页面仍未完全加载")
            return False
        except Exception as e:
            logger.debug(f"检查页面加载状态失败: {e}")
            return True  # 容错处理

    def browse_topics(self):
        """浏览话题（增强版）"""
        logger.info(f"\n{'='*50}")
        logger.info("🚀 开始执行升级任务")
        logger.info(f"{'='*50}")
        
        # 导航到最新话题页面
        try:
            logger.info("导航到最新话题页面...")
            self.page.get(f"{HOME_URL}latest")
            time.sleep(5)  # 等待页面加载
        except Exception as e:
            logger.error(f"导航失败: {e}")
            return False
        
        # 查找主题列表
        try:
            list_area = self.page.ele("@id=list-area", timeout=15)
            if not list_area:
                logger.error("未找到主题列表区域")
                return False
            
            topic_list = list_area.eles(".:title")
        except Exception as e:
            logger.error(f"查找主题列表失败: {e}")
            # 尝试备用选择器
            try:
                logger.info("尝试备用选择器...")
                topic_list = self.page.eles(".topic-list-item .title")
            except Exception as e2:
                logger.error(f"备用选择器也失败: {e2}")
                return False
        if not topic_list:
            logger.error("未找到主题帖")
            return False
        
        logger.info(f"发现 {len(topic_list)} 个主题帖，随机选择 {UPGRADE_CONFIG['topics_to_browse']} 个")
        
        selected_topics = random.sample(
            topic_list, 
            min(UPGRADE_CONFIG['topics_to_browse'], len(topic_list))
        )
        
        for i, topic in enumerate(selected_topics, 1):
            try:
                logger.info(f"[{i}/{len(selected_topics)}] 处理主题...")
                
                # 安全获取标题和URL
                try:
                    topic_url = topic.attr("href")
                    # 使用 JavaScript 获取文本，避免超时
                    topic_title = topic.owner.run_js("return arguments[0].textContent;", topic) or ""
                except Exception as e:
                    logger.debug(f"获取主题信息失败: {e}")
                    topic_url = topic.attr("href") if hasattr(topic, 'attr') else ""
                    topic_title = ""
                
                if not topic_url:
                    logger.debug("跳过无效主题")
                    continue
                
                self.browse_one_topic(topic_url, topic_title)
                
                # 随机延迟
                if i < len(selected_topics):
                    delay = random.uniform(5, 10)
                    time.sleep(delay)
            except Exception as e:
                logger.warning(f"处理主题时出错: {e}")
                continue
        
        return True

    @retry_decorator(retries=2, delay=2)
    def browse_one_topic(self, topic_url, topic_title: str = ""):
        """浏览单个话题"""
        new_page = self.browser.new_tab()
        try:
            new_page.get(topic_url)
            time.sleep(2)
            
            # 智能滚动浏览
            self.smart_scroll(new_page)
            
            # 点赞（每主题 1-2 次）
            if self.stats['likes_given'] < UPGRADE_CONFIG['likes_to_give']:
                liked = self.like_posts_in_topic(new_page, max_likes=2)
                if liked > 0:
                    logger.info(f"👍 点赞 {liked} 次 (总计:{self.stats['likes_given']})")
            
            # 回复（控制频率）
            if self.stats['replies_posted'] < UPGRADE_CONFIG['replies_to_post']:
                if random.random() < 0.3:  # 30% 概率回复
                    if self.reply_to_topic(new_page, topic_title):
                        logger.info(f"💬 回复成功 (总计:{self.stats['replies_posted']})")
            
            self.stats['topics_browsed'] += 1
            
        finally:
            new_page.close()

    def smart_scroll(self, page):
        """智能滚动浏览"""
        prev_url = None
        scroll_times = random.randint(3, 8)
        
        for i in range(scroll_times):
            scroll_distance = random.randint(450, 650)
            logger.debug(f"滚动 {i+1}/{scroll_times}: {scroll_distance}px")
            page.run_js(f"window.scrollBy(0, {scroll_distance})")
            
            self.stats['posts_read'] += 1
            
            # 10% 概率提前退出
            if random.random() < 0.1:
                logger.debug("随机提前退出浏览")
                break

            # 检查是否到底部
            try:
                at_bottom = page.run_js(
                    "window.scrollY + window.innerHeight >= document.body.scrollHeight"
                )
            except Exception:
                at_bottom = False
            try:
                current_url = page.url
            except Exception:
                current_url = None
            
            if current_url != prev_url:
                prev_url = current_url
            elif at_bottom and prev_url == current_url:
                logger.debug("已到达页面底部")
                break

            wait_time = random.uniform(1.5, 3)
            time.sleep(wait_time)

    def like_posts_in_topic(self, page, max_likes: int = 2) -> int:
        """在当前话题中点赞帖子（每主题1-2次）"""
        liked_count = 0
        try:
            # 等待页面稳定
            time.sleep(3)
            
            # 使用 JavaScript 直接点赞（避免元素失效）
            for attempt in range(max_likes):
                try:
                    result = page.run_js("""
                        var buttons = document.querySelectorAll('.discourse-reactions-reaction-button');
                        for (var i = 0; i < buttons.length; i++) {
                            var btn = buttons[i];
                            if (!btn.classList.contains('has-reaction') && !btn.classList.contains('reacted')) {
                                btn.scrollIntoView({block: 'center'});
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    
                    if result:
                        liked_count += 1
                        self.stats['likes_given'] += 1
                        logger.success(f"👍 点赞成功 ({self.stats['likes_given']})")
                        time.sleep(random.uniform(1.5, 2.5))
                        
                        if self.stats['likes_given'] >= UPGRADE_CONFIG['likes_to_give']:
                            break
                    else:
                        logger.debug("未找到可点赞的按钮")
                        break
                        
                except Exception as e:
                    logger.debug(f"点赞尝试失败:{e}")
                    continue
            
            return liked_count
        except Exception as e:
            logger.debug(f"点赞功能异常:{e}")
            return 0

    def reply_to_topic(self, page, topic_title: str = "") -> bool:
        """回复话题（增强版）"""
        try:
            logger.info(f"回复话题: {topic_title[:40] if topic_title else '...'}")
            
            # 等待页面稳定
            time.sleep(4)
            
            # 使用 JavaScript 直接点击回复按钮（避免元素失效）
            try:
                # 尝试多种选择器
                selectors = [
                    "button.reply.create",
                    "button.reply",
                    ".topic-footer-main-buttons button.reply"
                ]
                
                clicked = False
                for selector in selectors:
                    try:
                        result = page.run_js(f"""
                            var btn = document.querySelector('{selector}');
                            if (btn) {{
                                btn.scrollIntoView({{block: 'center'}});
                                btn.click();
                                return true;
                            }}
                            return false;
                        """)
                        
                        if result:
                            logger.debug(f"使用选择器 '{selector}' 点击回复按钮")
                            clicked = True
                            break
                    except Exception:
                        continue
                
                if not clicked:
                    logger.debug("未找到回复按钮")
                    return False
                
                time.sleep(3)
            except Exception as e:
                logger.debug(f"点击回复按钮失败:{e}")
                return False
            
            # 查找编辑器
            try:
                editor = page.ele("css:.d-editor-input", timeout=10)
                if not editor:
                    logger.debug("未找到编辑器")
                    return False
                
                # 滚动到编辑器
                page.run_js("arguments[0].scrollIntoView({block: 'center'});", editor)
                time.sleep(1)
                
                # 输入回复内容
                reply_text = random.choice(REPLY_TEMPLATES)
                editor.clear()
                editor.input(reply_text)
                time.sleep(2)
                
                # 查找提交按钮
                submit_btn = page.ele("css:button.create")
                if not submit_btn:
                    logger.debug("未找到提交按钮")
                    return False
                
                # 滚动到提交按钮并点击
                page.run_js("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                time.sleep(1)
                submit_btn.click()
                time.sleep(3)
                
                self.stats['replies_posted'] += 1
                logger.success(f"💬 回复成功: {reply_text} ({self.stats['replies_posted']})")
                return True
                
            except Exception as e:
                logger.debug(f"回复输入失败:{e}")
                return False
            
        except Exception as e:
            logger.debug(f"回复失败: {str(e)}")
            return False

    def print_connect_info(self):
        """打印连接信息"""
        logger.info("获取连接信息")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        }
        try:
            resp = self.session.get(
                "https://connect.linux.do/", headers=headers, impersonate="chrome136"
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table tr")
            info = []

            for row in rows:
                cells = row.select("td")
                if len(cells) >= 3:
                    project = cells[0].text.strip()
                    current = cells[1].text.strip() if cells[1].text.strip() else "0"
                    requirement = cells[2].text.strip() if cells[2].text.strip() else "0"
                    info.append([project, current, requirement])

            print("--------------Connect Info-----------------")
            print(tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty"))
        except Exception as e:
            logger.warning(f"获取连接信息失败: {e}")

    def send_notifications(self):
        """发送多渠道通知"""
        status_msg = (
            f"Linux.Do 升级任务完成 ✅\n"
            f"浏览话题: {self.stats['topics_browsed']}\n"
            f"阅读帖子: {self.stats['posts_read']}\n"
            f"给出点赞: {self.stats['likes_given']}\n"
            f"发布回复: {self.stats['replies_posted']}"
        )
        
        # Telegram 通知
        if TG_BOT_TOKEN and TG_CHAT_ID:
            try:
                tg_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
                tg_data = {
                    "chat_id": TG_CHAT_ID,
                    "text": status_msg,
                    "parse_mode": "HTML"
                }
                response = requests.post(tg_url, json=tg_data, timeout=10, impersonate="chrome136")
                response.raise_for_status()
                logger.success("✅ Telegram 通知发送成功")
            except Exception as e:
                logger.warning(f"⚠️ Telegram 通知发送失败: {e}")
        
        # Gotify 通知
        if GOTIFY_URL and GOTIFY_TOKEN:
            try:
                response = requests.post(
                    f"{GOTIFY_URL}/message",
                    params={"token": GOTIFY_TOKEN},
                    json={"title": "Linux.Do 升级任务", "message": status_msg, "priority": 5},
                    timeout=10,
                    impersonate="chrome136"
                )
                response.raise_for_status()
                logger.success("✅ Gotify 通知发送成功")
            except Exception as e:
                logger.warning(f"⚠️ Gotify 通知发送失败: {e}")
        
        # Server 酱³ 通知
        if SC3_PUSH_KEY:
            match = re.match(r"sct(\d+)t", SC3_PUSH_KEY, re.I)
            if not match:
                logger.warning("⚠️ SC3_PUSH_KEY 格式错误")
            else:
                uid = match.group(1)
                url = f"https://{uid}.push.ft07.com/send/{SC3_PUSH_KEY}"
                params = {"title": "Linux.Do 升级任务", "desp": status_msg}
                
                try:
                    response = requests.get(url, params=params, timeout=10, impersonate="chrome136")
                    response.raise_for_status()
                    logger.success("✅ Server 酱³ 通知发送成功")
                except Exception as e:
                    logger.warning(f"⚠️ Server 酱³ 通知发送失败: {e}")

    def run(self):
        """主运行函数"""
        try:
            logger.info("==== Linux.Do 快速升级脚本开始 ====")
            
            # 1. 登录
            login_res = self.login()
            if not login_res:
                logger.error("登录验证失败")
                return 1

            # 2. 浏览话题
            if BROWSE_ENABLED:
                try:
                    browse_res = self.browse_topics()
                    if not browse_res:
                        logger.error("浏览话题失败")
                        # 保存调试截图
                        try:
                            screenshot_path = "/ql/data/scripts/linuxdo_debug.png"
                            self.page.get_screenshot(path=screenshot_path)
                            logger.info(f"已保存调试截图: {screenshot_path}")
                        except Exception as e:
                            logger.debug(f"保存截图失败: {e}")
                        return 2
                    logger.success("完成浏览任务")
                except Exception as e:
                    logger.error(f"浏览任务异常: {e}")
                    import traceback
                    traceback.print_exc()
                    return 2

            # 3. 输出统计
            logger.info(f"\n{'='*50}")
            logger.info("📊 今日任务完成统计:")
            logger.info(f"  - 浏览话题: {self.stats['topics_browsed']}")
            logger.info(f"  - 阅读帖子: {self.stats['posts_read']}")
            logger.info(f"  - 给出点赞: {self.stats['likes_given']}")
            logger.info(f"  - 发布回复: {self.stats['replies_posted']}")
            logger.info(f"{'='*50}\n")

            # 4. 发送通知
            self.send_notifications()
            
            logger.info("==== Linux.Do 快速升级脚本结束 ====")
            return 0

        except Exception as e:
            logger.error(f"脚本异常: {e}")
            import traceback
            traceback.print_exc()
            return 9

        finally:
            try:
                self.page.close()
                self.browser.quit()
            except Exception:
                pass


if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("Please set LINUXDO_USERNAME and LINUXDO_PASSWORD")
        exit(1)
    
    app = LinuxDoUpgrade()
    exit(app.run())
