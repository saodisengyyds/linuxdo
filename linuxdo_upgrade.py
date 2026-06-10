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
import json


# ================== 升级配置 ==================
UPGRADE_CONFIG = {
    "topics_to_browse": 15,        # 每次浏览话题数（加速升级）
    "likes_to_give": 5,            # 每次点赞数
    "replies_to_post": 2,          # 每次回复数（谨慎设置）
}

# 回复内容池
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
WECHAT_API_URL = os.environ.get("WECHAT_API_URL")   # 自定义微信 API 地址
WECHAT_AUTH_TOKEN = os.environ.get("WECHAT_AUTH_TOKEN") # 自定义微信 Token
LINUXDO_PROXY = os.environ.get("LINUXDO_PROXY")  # 代理设置

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linuxdo_cookies.json")


class LinuxDoUpgrade:
    def __init__(self) -> None:
        from sys import platform
        
        # Kill leftover Chromium instances first to avoid WebSocket 404
        try:
            import os, time
            os.system("pkill -9 -f chromium")
            time.sleep(1)
        except:
            pass

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
            .set_argument("--disable-gpu")
            .set_argument("--disable-dev-shm-usage")
            .set_argument("--disable-extensions")
            .set_argument("--window-size=1920,1080")
        )
        if LINUXDO_PROXY:
            co.set_proxy(LINUXDO_PROXY)
        co.set_user_agent(
            f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()
        # 使用 eager 模式，DOM 加载完即可，不用等待所有资源 loaded
        self.page.set.load_mode.eager()
        self.session = requests.Session()
        if LINUXDO_PROXY:
            self.session.proxies = {"http": LINUXDO_PROXY, "https": LINUXDO_PROXY}
            logger.info(f"已启用代理: {LINUXDO_PROXY}")
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

    def load_cookies(self):
        """加载本地 Cookie"""
        if not os.path.exists(COOKIE_FILE):
             return False
        
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            # 注入到 Session
            for cookie in cookies:
                # 简单处理：将 dict 转换为 cookie jar 所需格式，或者直接 set
                # 这里假设 cookie 是 list of dict
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', '.linux.do'))
            
            # 注入到 Browser
            self.page.set.cookies(cookies)
            logger.info(f"已加载本地 Cookie ({len(cookies)} 个)")
            return True
        except Exception as e:
            logger.warning(f"加载 Cookie 失败: {e}")
            return False

    def save_cookies(self):
        """保存 Cookie 到本地"""
        try:
            # DrissionPage 较新版本中 self.page.cookies 不是对象就是方法
            if callable(self.page.cookies):
                cookies_list = self.page.cookies(as_dict=False)
            else:
                try:
                    cookies_list = self.page.cookies.as_list()
                except:
                    # 对于一些特殊版本，直接取
                    cookies_list = getattr(self.page, 'cookies_to_dict', lambda: [])()
                    
            if not isinstance(cookies_list, list):
                # 尝试其他方式获取
                cookies_dict = self.page.cookies if isinstance(self.page.cookies, dict) else (self.page.cookies() if callable(self.page.cookies) else {})
                cookies_list = [{'name': k, 'value': v, 'domain': '.linux.do'} for k, v in cookies_dict.items()]

            # 过滤只保存 linux.do 相关
            filtered_cookies = [c for c in cookies_list if isinstance(c, dict) and 'linux.do' in c.get('domain', '')]
            
            if filtered_cookies:
                with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(filtered_cookies, f, indent=2, ensure_ascii=False)
                logger.success("Cookie 已保存到本地")
        except Exception as e:
            logger.warning(f"保存 Cookie 失败: {e}")

    @retry_decorator(retries=2, delay=2)
    def login(self):
        """登录 Linux.Do (DrissionPage 浏览器模拟)"""
        logger.info("开始登录流程...")
        
        # 尝试 Cookie 登录
        if self.load_cookies():
            logger.info("尝试使用 Cookie 验证登录...")
            try:
                self.page.get(HOME_URL)
                time.sleep(5)
                if self.check_login_status():
                    logger.success("Cookie 登录验证成功！")
                    return True
                else:
                    logger.warning("Cookie 失效，转为密码登录")
            except Exception as e:
                logger.warning(f"Cookie 登录尝试异常: {e}")
        
        # 密码登录流程
        logger.info("执行账号密码登录 (浏览器模式)...")
        try:
            self.page.get(LOGIN_URL)
            time.sleep(3)
            
            # 检测 Cloudflare
            if "Just a moment" in self.page.title:
                logger.warning("检测到 Cloudflare 验证页面，等待自动跳过...")
                time.sleep(10)
            
            # 等待登录框出现
            logger.info("寻找登录输入框...")
            
            # 输入用户名
            user_input = self.page.ele("#login-account-name", timeout=10)
            if not user_input:
                # 尝试点击登录按钮唤起弹窗 (如果直接访问 login url 没有显示输入框)
                login_btn_top = self.page.ele(".login-button")
                if login_btn_top:
                    login_btn_top.click()
                    time.sleep(2)
                    user_input = self.page.ele("#login-account-name", timeout=10)
            
            if not user_input:
                logger.error("未找到用户名输入框")
                return False
                
            user_input.clear()
            user_input.input(USERNAME)
            time.sleep(0.5)
            
            # 输入密码
            pwd_input = self.page.ele("#login-account-password")
            if not pwd_input:
                logger.error("未找到密码输入框")
                return False
                
            pwd_input.clear()
            pwd_input.input(PASSWORD)
            time.sleep(0.5)
            
            # 点击登录
            login_btn = self.page.ele("#login-button")
            if not login_btn:
                logger.error("未找到登录提交按钮")
                return False
                
            login_btn.click()
            logger.info("已点击登录按钮，等待跳转...")
            
            # 等待登录成功
            for i in range(20):
                time.sleep(1)
                if self.check_login_status():
                    logger.success("登录成功!")
                    
                    # 登录成功后同步 Cookie 到 session (用于通知等)
                    self.sync_cookies_to_session()
                    # 保存 Cookie 到本地
                    self.save_cookies()
                    return True
            
            logger.error("登录超时，未检测到登录成功状态")
            return False

        except Exception as e:
            logger.error(f"登录过程发生异常: {e}")
            return False

    def sync_cookies_to_session(self):
        """同步浏览器 Cookie 到 requests session"""
        try:
            cookies = {}
            if callable(self.page.cookies):
                cookies = self.page.cookies()
            else:
                try:
                    cookies = self.page.cookies.as_dict()
                except:
                    pass
            
            if cookies and isinstance(cookies, dict):
                self.session.cookies.update(cookies)
                logger.info(f"已同步 {len(cookies)} 个 Cookie 到 Session")
            else:
                logger.warning("未获取到有效的 Cookie 字典形式")
        except Exception as e:
            logger.warning(f"同步 Cookie 失败: {e}")
            
    def check_login_status(self):
        """检查页面是否已登录"""
        try:
            user_ele = self.page.ele("@id=current-user")
            if user_ele:
                return True
                
            if "avatar" in self.page.html:
                # 再次确认不是默认头像或登录按钮
                return True
                
            return False
        except:
            return False
    
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
            # 设置超时和重试
            self.page.get(f"{HOME_URL}latest", timeout=20, retry=2)
            time.sleep(5)  # 等待动态内容渲染
        except Exception as e:
            logger.error(f"导航失败: {e}")
            # 尝试刷新一次
            try:
                logger.info("尝试刷新页面...")
                self.page.refresh()
                time.sleep(5)
            except Exception as e2:
                logger.error(f"刷新失败: {e2}")
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
            # 调试：打印页面标题和少量 HTML
            logger.debug(f"当前页面标题: {self.page.title}")
            logger.debug(f"页面源码前 500 字符: {self.page.html[:500]}")
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
            time.sleep(2)
            
            # 使用 JavaScript 直接点赞（扩大选择器范围）
            for attempt in range(max_likes):
                try:
                    result = page.run_js("""
                        // 多种可能的点赞按钮选择器
                        const selectors = [
                            '.discourse-reactions-reaction-button', 
                            '.btn-toggle-reaction-like', 
                            'button[title="点赞此帖子"]',
                            'button[title="点赞"]',
                            'button[aria-label="点赞此帖子"]',
                            '.widget-button.btn-flat.like',
                            '.actions .like',
                            '#post_1 .discourse-reactions-reaction-button',
                            'button.discourse-reactions-reaction-button',
                            'button .d-icon-heart',
                            'button.react-button'
                        ];
                        
                        // 寻找所有可见的按钮
                        for (let sel of selectors) {
                            let buttons = document.querySelectorAll(sel);
                            for (let i = 0; i < buttons.length; i++) {
                                let btn = buttons[i];
                                // 检查是否已点赞
                                if (!btn.classList.contains('has-reaction') && 
                                    !btn.classList.contains('reacted') && 
                                    !btn.classList.contains('has-used-main-reaction') &&
                                    !btn.title.includes('取消') &&
                                    btn.offsetParent !== null) { // 确保可见
                                    
                                    btn.scrollIntoView({block: 'center'});
                                    btn.click();
                                    
                                    // 给刚点赞的按钮加上标记，防止同一次脚本重复点击
                                    btn.classList.add('has-used-main-reaction');
                                    return true;
                                }
                            }
                        }
                        return false;
                    """)
                    
                    if result:
                        liked_count += 1
                        self.stats['likes_given'] += 1
                        logger.success(f"👍 点赞成功 (JS) ({self.stats['likes_given']})")
                        time.sleep(random.uniform(1.5, 2.5))
                        
                        if self.stats['likes_given'] >= UPGRADE_CONFIG['likes_to_give']:
                            break
                    else:
                        # Fallback: 使用 DrissionPage 原生查找
                        try:
                            # 查找所有类名包含 reaction-button 的按钮
                            like_btns = page.eles("css:.discourse-reactions-reaction-button")
                            if not like_btns:
                                like_btns = page.eles("css:button[title*='点赞']")
                            if not like_btns:
                                like_btns = page.eles("css:.btn-toggle-reaction-like")
                            if not like_btns:
                                like_btns = page.eles("xpath://button[contains(@class, 'reaction-button') or contains(@class, 'like')]")
                            if not like_btns:
                                like_btns = page.eles("xpath://button[.//svg[contains(@class, 'd-icon-heart')]]")
                                
                            found_and_clicked = False
                            for btn in like_btns:
                                classes = btn.attr('class') or ''
                                title = btn.attr('title') or ''
                                if 'has-reaction' not in classes and 'reacted' not in classes and '取消' not in title:
                                    page.run_js("arguments[0].scrollIntoView({block: 'center'});", btn)
                                    time.sleep(0.5)
                                    btn.click()
                                    liked_count += 1
                                    self.stats['likes_given'] += 1
                                    logger.success(f"👍 点赞成功 (DP) ({self.stats['likes_given']})")
                                    time.sleep(random.uniform(1.5, 2.5))
                                    found_and_clicked = True
                                    break
                                    
                            if not found_and_clicked:
                                logger.debug("DP也未找到未点赞的按钮")
                                break
                        except Exception as inner_e:
                            logger.debug(f"DP寻找点赞按钮失败: {inner_e}")
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
                    ".topic-footer-main-buttons button.reply",
                    ".topic-footer-main-buttons .btn.create",
                    "#topic-footer-buttons .reply",
                    "button[title='回复此话题']",
                    "button[aria-label='回复此话题']",
                    "button.create[title*='回复']",
                    ".reply-to-post",
                    "button.btn-primary.create",
                    "button[title='回复']",
                    "button[aria-label='回复']",
                    "button .d-icon-reply",
                    "button.create"
                ]
                
                # 策略1：直接查找
                clicked = self._try_click_reply(page, selectors)
                
                # 策略2：如果未找到，强制滚动到底部加载 topic-footer
                if not clicked:
                    logger.info("未找到回复按钮，尝试滚动到底部...")
                    page.run_js("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(3)
                    clicked = self._try_click_reply(page, selectors)
                
                if not clicked:
                    logger.debug("最终未找到回复按钮")
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

    def _try_click_reply(self, page, selectors):
        """辅助函数：尝试点击各类回复按钮"""
        # Fallback to direct DrissionPage element finding as well
        for selector in selectors:
            try:
                result = page.run_js(f"""
                    var btn = document.querySelector('{selector}');
                    if (btn && btn.offsetParent !== null) {{ // ensure visible
                        btn.scrollIntoView({{block: 'center'}});
                        btn.click();
                        return true;
                    }}
                    return false;
                """)
                if result:
                    logger.debug(f"使用选择器 JS '{selector}' 点击回复按钮")
                    return True
            except Exception:
                pass
                
            try:
                btn = page.ele(f"css:{selector}")
                if btn and btn.states.is_displayed:
                    page.run_js("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.5)
                    btn.click()
                    logger.debug(f"使用 DrissionPage '{selector}' 点击回复按钮")
                    return True
            except:
                continue
                
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
        status_msg = (
            f"Linux.Do 升级任务完成 ✅\n"
            f"浏览话题: {self.stats['topics_browsed']}\n"
            f"阅读帖子: {self.stats['posts_read']}\n"
            f"给出点赞: {self.stats['likes_given']}\n"
            f"发布回复: {self.stats['replies_posted']}"
        )
        # 尝试使用青龙自带通知
        try:
            import sys
            if '/ql/scripts' not in sys.path:
                sys.path.append('/ql/scripts')
            if '/ql/data/scripts' not in sys.path:
                sys.path.append('/ql/data/scripts')

            from notify import send
            send("Linux.Do 升级任务", status_msg)
            logger.success("✅ 已通过青龙自带 notify.py 发送通知")
        except Exception as e:
            logger.info(f"未找到青龙 notify.py 或发送失败 ({e})，尝试直接使用 TG 环境变量推送...")
            import os
            import requests
            tg_token = os.environ.get("TG_BOT_TOKEN", "").strip()
            tg_chat_id = os.environ.get("TG_CHAT_ID", "").strip()
            if tg_token and tg_chat_id:
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                payload = {"chat_id": tg_chat_id, "text": status_msg, "disable_web_page_preview": True}
                try:
                    r = requests.post(url, json=payload, timeout=15)
                    if r.status_code == 200:
                        logger.success("✅ 已通过 Telegram 直接发送通知")
                    else:
                        logger.warning(f"⚠️ Telegram 发送失败: {r.text}")
                except Exception as ex:
                    logger.warning(f"⚠️ Telegram 请求异常: {ex}")
            else:
                logger.info("未配置 TG_BOT_TOKEN 环境变量，已完全跳过推送。")

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
