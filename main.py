# -- coding: utf-8 --
"""
使用DrissionPage重写的NodeSeek自动签到和评论脚本
Copyright (c) 2024
Licensed under the MIT License.
"""

import os
import time
import random
import functools
import signal
import sys
import argparse
from loguru import logger
from DrissionPage import ChromiumPage, ChromiumOptions

# 随机评论文本
RANDOM_COMMENTS = ["bd", "绑定", "帮顶"]

# 配置loguru日志
logger.remove()  # 移除默认处理器
logger.add(
    sink=lambda msg: print(msg),
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
)
logger.add(
    sink="nodeseek.log",
    rotation="1 MB",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)


def retry(max_retries=3, delay=1):
    """
    重试装饰器，用于自动重试可能失败的操作

    Args:
        max_retries: 最大重试次数
        delay: 重试间隔秒数
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    logger.warning(
                        f"函数 {func.__name__} 执行失败 ({retries}/{max_retries}): {str(e)}"
                    )
                    if retries >= max_retries:
                        logger.error(
                            f"函数 {func.__name__} 已达到最大重试次数 {max_retries}，停止重试"
                        )
                        raise
                    time.sleep(delay)

        return wrapper

    return decorator


class NodeSeekDaily:
    """NodeSeek自动签到和评论工具"""

    def __init__(self, username=None, password=None):
        """初始化配置和环境变量"""
        # 从环境变量获取配置
        self.cookie = os.environ.get("NS_COOKIE") or os.environ.get("COOKIE")
        self.headless = os.environ.get("HEADLESS", "true").lower() == "true"
        self.use_random = os.environ.get("NS_RANDOM", "false").lower() == "true"
        self.username = (
            username or os.environ.get("NS_USERNAME") or os.environ.get("USERNAME")
        )
        self.password = (
            password or os.environ.get("NS_PASSWORD") or os.environ.get("PASSWORD")
        )

        if not (self.cookie or (self.username and self.password)):
            logger.error(
                "未找到cookie或账号密码配置，请设置NS_COOKIE/COOKIE或NS_USERNAME+NS_PASSWORD环境变量"
            )
            raise ValueError("Cookie或账号密码未配置")

        self.page = None
        logger.info("NodeSeekDaily初始化完成")

    def login(self):
        """
        登录方法：优先cookie，失败自动账号密码
        """
        # 先尝试cookie登录
        if self.cookie:
            logger.info("尝试使用cookie登录...")
            self.page.get("https://www.nodeseek.com")
            time.sleep(2)
            self.page.set.cookies(self.cookie)
            self.page.refresh()
            time.sleep(2)
            if self._is_logged_in():
                logger.info("Cookie验证成功，已登录")
                return True
            else:
                logger.warning("Cookie登录失败，尝试账号密码登录...")
        logger.error("未配置有效的cookie或账号密码，无法登录")
        return False

    def _is_logged_in(self):
        """检测是否已登录"""
        try:
            user_card = self.page.ele(
                "css:#nsk-right-panel-container > div.user-card", timeout=3
            )
            return bool(user_card)
        except Exception:
            return False

    @retry(max_retries=3, delay=2)
    def setup_browser(self):
        """
        初始化并配置浏览器（不做登录）
        """
        try:
            logger.info("开始初始化浏览器...")
            options = ChromiumOptions()
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            options.set_user_agent(user_agent)
            if self.headless:
                logger.info("启用无头模式...")
                options.headless = True
                options.set_window_size(1920, 1080)
                options.set_argument("--disable-blink-features=AutomationControlled")
                options.set_argument("--disable-gpu")
            logger.info("正在启动Chrome...")
            self.page = ChromiumPage(addr_or_opts=options)
            if self.headless:
                self.page.run_js(
                    'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                )
            logger.info("Chrome启动成功")
            return True
        except Exception as e:
            logger.exception(f"设置浏览器时出错: {str(e)}")
            return False

    def __del__(self):
        """析构函数，确保浏览器正确关闭"""
        try:
            if self.page:
                logger.info("关闭浏览器...")
                self.page.quit()
        except Exception as e:
            logger.warning(f"关闭浏览器时出错: {str(e)}")

    @retry(max_retries=3, delay=2)
    def sign_in(self):
        """
        执行签到功能，点击签到图标并选择奖励

        Returns:
            bool: 签到是否成功
        """
        try:
            logger.info("开始执行签到操作...")

            # 确保在主页
            self.page.get("https://www.nodeseek.com")
            time.sleep(3)  # 等待页面加载完成

            # 查找签到图标
            logger.info("开始查找签到图标...")
            sign_icon = self.page.ele("xpath://span[@title='签到']", timeout=10)

            if not sign_icon:
                logger.warning("未找到签到图标，可能已经签到过了")
                return False

            logger.info("找到签到图标，准备点击...")

            # 点击签到图标
            try:
                sign_icon.click()
                logger.info("签到图标点击成功")
            except Exception as e:
                logger.warning(f"常规点击失败: {str(e)}，尝试使用JavaScript点击")
                self.page.run_js("arguments[0].click();", sign_icon.inner_ele)
                logger.info("JavaScript点击签到图标成功")

            # 等待页面跳转和加载
            time.sleep(3)  # 等待页面加载完成

            # 打印当前URL
            logger.debug(f"当前页面URL: {self.page.url}")

            # 选择奖励
            try:
                # 根据配置选择"试试手气"或"鸡腿 x 5"
                if self.use_random:
                    logger.info("尝试点击'试试手气'按钮...")
                    lucky_btn = self.page.ele(
                        "xpath://button[contains(text(), '试试手气')]", timeout=5
                    )
                    if lucky_btn:
                        lucky_btn.click()
                        logger.info("'试试手气'按钮点击成功")
                else:
                    logger.info("尝试点击'鸡腿 x 5'按钮...")
                    chicken_btn = self.page.ele(
                        "xpath://button[contains(text(), '鸡腿 x 5')]", timeout=5
                    )
                    if chicken_btn:
                        chicken_btn.click()
                        logger.info("'鸡腿 x 5'按钮点击成功")

                # 等待确认框消失
                time.sleep(2)
                logger.info("签到完成")
                return True

            except Exception as e:
                logger.warning(f"选择奖励失败或已签到: {str(e)}")
                # 可能已经签到过了，也视为成功
                return True

        except Exception as e:
            logger.exception(f"签到过程中出错: {str(e)}")
            # 记录当前页面URL和部分源码，便于调试
            try:
                logger.debug(f"当前页面URL: {self.page.url}")
                logger.debug(f"页面源码片段: {self.page.html[:500]}...")
            except:
                pass
            return False

    @retry(max_retries=3, delay=2)
    def comment_posts(self, max_posts=5):
        """
        执行随机评论功能，访问交易区并随机评论帖子

        Args:
            max_posts: 最大评论帖子数量

        Returns:
            int: 成功评论的帖子数量
        """
        try:
            logger.info("开始执行评论操作...")

            # 访问交易区
            target_url = "https://www.nodeseek.com/categories/trade"
            logger.info(f"正在访问交易区: {target_url}")
            self.page.get(target_url)
            time.sleep(3)  # 等待页面加载完成
            logger.info("交易区页面加载完成")

            # 获取帖子列表
            logger.info("获取帖子列表...")
            post_items = self.page.eles("css:.post-list-item", timeout=10)
            logger.info(f"成功获取到 {len(post_items)} 个帖子")

            if not post_items:
                logger.warning("未找到可评论的帖子")
                return 0

            # 过滤掉置顶帖
            filtered_posts = []
            for post in post_items:
                # 检查帖子是否是置顶帖
                if not post.ele("css:.pined", timeout=0.5):
                    filtered_posts.append(post)

            logger.info(f"过滤后有 {len(filtered_posts)} 个非置顶帖")

            valid_posts = []
            # 只要特定内容的帖子 标题包含出 但不是已出
            for post in filtered_posts:
                if (
                    "出" in post.ele("css:.post-title").text
                    and "已出" not in post.ele("css:.post-title").text
                ):
                    valid_posts.append(post)

            logger.info(f"符合条件的帖子有 {len(valid_posts)} 个")

            if not valid_posts:
                logger.warning("没有找到非置顶帖")
                return 0

            # 随机选择帖子，但不超过max_posts或可用数量
            post_count = min(max_posts, len(valid_posts))
            selected_posts = random.sample(valid_posts, post_count)

            # 收集帖子URL
            selected_urls = []
            for post in selected_posts:
                try:
                    post_link = post.ele("css:.post-title a")
                    if post_link:
                        selected_urls.append(post_link.attr("href"))
                except Exception as e:
                    logger.warning(f"获取帖子链接失败: {str(e)}")
                    continue

            logger.info(f"已选择 {len(selected_urls)} 个帖子进行评论")

            # 记录是否已加鸡腿
            chicken_added = False
            comment_count = 0

            # 遍历选中的帖子URL并评论
            for i, post_url in enumerate(selected_urls):
                try:
                    logger.info(f"正在处理第 {i + 1}/{len(selected_urls)} 个帖子")

                    # 访问帖子页面
                    if not post_url.startswith("http"):
                        full_url = f"https://www.nodeseek.com{post_url}"
                    else:
                        full_url = post_url

                    logger.info(f"访问帖子: {full_url}")
                    self.page.get(full_url)
                    time.sleep(3)  # 等待页面加载完成

                    # 如果还没有加过鸡腿，尝试加鸡腿
                    # if not chicken_added:
                    #     chicken_added = self.add_chicken_leg()

                    # 查找评论编辑器
                    logger.info("查找评论编辑器...")
                    editor = self.page.ele("css:.CodeMirror", timeout=10)

                    if not editor:
                        logger.warning("未找到评论编辑器，跳过此帖子")
                        continue

                    # 点击编辑器获取焦点
                    logger.info("点击编辑器获取焦点...")
                    editor.click()
                    time.sleep(0.5)

                    # 随机选择评论文本
                    input_text = random.choice(RANDOM_COMMENTS)
                    logger.info(f"准备输入评论内容: {input_text}")

                    # 清空编辑器并输入评论
                    self.page.run_js("""
                    var editor = document.querySelector(".CodeMirror").CodeMirror;
                    editor.setValue("");
                    editor.refresh();
                    """)
                    time.sleep(0.5)

                    # 模拟真实用户输入，每个字符之间有随机延迟
                    for char in input_text:
                        # 使用JavaScript注入字符
                        self.page.run_js(f'''
                        var editor = document.querySelector(".CodeMirror").CodeMirror;
                        editor.replaceSelection("{char}");
                        ''')
                        # 随机延迟模拟真实输入
                        time.sleep(random.uniform(0.1, 0.3))

                    # 等待确保内容已输入
                    time.sleep(1)

                    # 查找并点击发布评论按钮
                    logger.info("寻找发布评论按钮...")
                    submit_btn = self.page.ele(
                        "xpath://button[contains(@class, 'submit') and contains(@class, 'btn') and contains(text(), '发布评论')]",
                        timeout=5,
                    )

                    if not submit_btn:
                        logger.warning("未找到发布评论按钮，跳过此帖子")
                        continue

                    # 点击发布按钮
                    submit_btn.click()
                    logger.info(f"已在帖子 {full_url} 中提交评论")

                    # 随机等待一段时间再处理下一个帖子
                    wait_time = random.uniform(2, 5)
                    logger.info(f"等待 {wait_time:.1f} 秒后继续...")
                    time.sleep(wait_time)

                    comment_count += 1

                except Exception as e:
                    logger.warning(f"评论帖子时出错: {str(e)}")
                    continue

            logger.info(f"评论任务完成，共成功评论 {comment_count} 个帖子")
            return comment_count

        except Exception as e:
            logger.exception(f"评论操作执行出错: {str(e)}")
            return 0

    @retry(max_retries=2, delay=1)
    def add_chicken_leg(self, post_url=None):
        """
        给帖子加鸡腿

        Args:
            post_url: 帖子URL，如果为None则使用当前页面

        Returns:
            bool: 加鸡腿是否成功
        """
        try:
            logger.info("开始执行加鸡腿操作...")

            # 如果提供了URL，先访问该页面
            if post_url:
                if not post_url.startswith("http"):
                    full_url = f"https://www.nodeseek.com{post_url}"
                else:
                    full_url = post_url

                logger.info(f"访问帖子: {full_url}")
                self.page.get(full_url)
                time.sleep(3)  # 等待页面加载完成

            # 查找加鸡腿按钮
            logger.info("查找加鸡腿按钮...")
            chicken_btn = self.page.ele(
                "xpath://div[@class='nsk-post']//div[@title='加鸡腿'][1]", timeout=5
            )

            if not chicken_btn:
                logger.warning("未找到加鸡腿按钮，可能帖子不支持加鸡腿")
                return False

            # 确保按钮可见
            logger.info("准备点击加鸡腿按钮...")
            self.page.run_js(
                "arguments[0].scrollIntoView({block: 'center'});", chicken_btn.inner_ele
            )
            time.sleep(0.5)

            # 点击加鸡腿按钮
            chicken_btn.click()
            logger.info("加鸡腿按钮点击成功")

            # 等待确认对话框出现
            logger.info("等待确认对话框...")
            confirm_dialog = self.page.ele("css:.msc-confirm", timeout=5)

            if not confirm_dialog:
                logger.warning("未出现确认对话框")
                return False

            # 检查是否是7天前的帖子
            try:
                error_title = self.page.ele(
                    "xpath://h3[contains(text(), '该评论创建于7天前')]", timeout=1
                )
                if error_title:
                    logger.info("该帖子超过7天，无法加鸡腿")
                    # 点击确认按钮关闭对话框
                    ok_btn = self.page.ele("css:.msc-confirm .msc-ok")
                    if ok_btn:
                        ok_btn.click()
                        logger.info("已关闭对话框")
                    return False
            except Exception:
                # 没有找到错误标题，继续正常流程
                pass

            # 点击确认按钮
            logger.info("点击确认按钮...")
            ok_btn = self.page.ele("css:.msc-confirm .msc-ok", timeout=3)
            if ok_btn:
                ok_btn.click()
                logger.info("确认加鸡腿成功")
            else:
                logger.warning("未找到确认按钮")
                return False

            # 等待确认对话框消失
            logger.info("等待对话框消失...")
            time.sleep(3)  # 等待对话框消失

            logger.info("加鸡腿操作完成")
            return True

        except Exception as e:
            logger.warning(f"加鸡腿操作失败: {str(e)}")
            return False

    def run_all(self, max_posts=5):
        """
        执行所有任务

        Args:
            max_posts: 最大评论帖子数量

        Returns:
            bool: 所有任务是否成功完成
        """
        try:
            # 初始化浏览器
            if not self.setup_browser():
                logger.error("浏览器初始化失败，程序退出")
                return False

            # 登录
            if not self.login():
                logger.error("登录失败，程序退出")
                return False

            # 执行评论
            comment_count = self.comment_posts(max_posts=2)  # 暂时使用2个帖子
            logger.info(f"共成功评论 {comment_count} 个帖子")

            # 执行签到
            sign_result = self.sign_in()
            if sign_result:
                logger.info("签到流程执行成功")
            else:
                logger.warning("签到流程执行失败或已签到")

            logger.info("所有任务执行完成")
            return True
        except Exception as e:
            logger.exception(f"执行所有任务时出错: {str(e)}")
            return False


def signal_handler(sig, frame):
    """
    信号处理函数，用于优雅地退出程序
    """
    logger.info("接收到终止信号，正在退出...")
    sys.exit(0)


def parse_args():
    """
    解析命令行参数

    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(description="NodeSeek自动签到和评论工具")
    parser.add_argument("--sign-only", action="store_true", help="仅执行签到操作")
    parser.add_argument("--comment-only", action="store_true", help="仅执行评论操作")
    parser.add_argument(
        "--headless", action="store_true", help="启用无头模式（覆盖环境变量设置）"
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="禁用无头模式（覆盖环境变量设置）",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help='签到时使用"试试手气"选项（覆盖环境变量设置）',
    )
    parser.add_argument("--max-posts", type=int, default=5, help="最大评论帖子数量")

    return parser.parse_args()


def main():
    """主函数"""
    try:
        # 注册信号处理
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # 解析命令行参数
        args = parse_args()

        logger.info("开始执行NodeSeek自动签到和评论")
        node_seek = NodeSeekDaily()

        # 根据命令行参数覆盖默认配置
        if args.headless is not None:
            node_seek.headless = args.headless
            logger.info(f"通过命令行参数{'启用' if args.headless else '禁用'}无头模式")

        if args.random:
            node_seek.use_random = True
            logger.info("通过命令行参数启用随机签到奖励")

        # 初始化浏览器
        if not node_seek.setup_browser():
            logger.error("浏览器初始化失败，程序退出")
            return False

        # 登录
        if not node_seek.login():
            logger.error("登录失败，程序退出")
            return False

        # 根据命令行参数执行指定任务
        if args.sign_only:
            logger.info("仅执行签到任务")
            sign_result = node_seek.sign_in()
            if sign_result:
                logger.info("签到流程执行成功")
            else:
                logger.warning("签到流程执行失败或已签到")
        elif args.comment_only:
            logger.info("仅执行评论任务")
            comment_count = node_seek.comment_posts(max_posts=args.max_posts)
            logger.info(f"共成功评论 {comment_count} 个帖子")
        else:
            # 执行所有任务
            logger.info("执行所有任务")
            if not node_seek.run_all(max_posts=args.max_posts):
                return False

        logger.info("NodeSeek任务执行完成")
        return True
    except Exception as e:
        logger.exception(f"程序执行出错: {str(e)}")
        return False
    finally:
        # 确保浏览器正确关闭
        if "node_seek" in locals() and node_seek.page:
            logger.info("清理资源，关闭浏览器...")
            try:
                node_seek.page.quit()
            except:
                pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
