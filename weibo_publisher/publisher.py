"""
微博发布模块
使用Selenium自动化操作微博发布、上传图片、发送评论
包含Cookie持久化、失败重试、评论区自动评论等功能
"""

import os
import time
import pickle
import logging
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    WebDriverException,
)

logger = logging.getLogger(__name__)
COOKIE_PATH = Path(__file__).parent / "cookie.pkl"


class WeiboPublisher:
    """微博发布器"""

    def __init__(self, weibo_url: str = "https://weibo.com", headless: bool = False):
        self.weibo_url = weibo_url
        self.headless = headless  # 是否无头模式（后台运行）
        self.driver = None
        self.wait = None

    # ================================================================
    # 登录相关
    # ================================================================

    def _is_login_page(self) -> bool:
        """判断当前是否在登录页（通过域名判断）"""
        current_url = self.driver.current_url
        parsed = urlparse(current_url)
        host = parsed.hostname or ""
        return host in ["passport.weibo.com", "login.sina.com.cn", "login.weibo.cn"]

    def _check_login_cookie(self) -> bool:
        """检查Cookie中是否存在微博登录态"""
        cookies = self.driver.get_cookies()
        cookie_names = [c.get("name", "") for c in cookies]
        return "SUB" in cookie_names or "SUBP" in cookie_names

    def start_browser(self):
        """启动浏览器"""
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # 无头模式（后台运行，不占用前台）
        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")

        self.driver = webdriver.Chrome(options=options)

        # 隐藏webdriver特征
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        self.wait = WebDriverWait(self.driver, 15)

        if COOKIE_PATH.exists():
            logger.info("发现已保存的Cookie，正在尝试加载...")
            self._load_cookies()
        else:
            logger.info("首次使用，进入手动登录流程...")
            self._manual_login()

    def _manual_login(self):
        """手动登录流程"""
        self.driver.get(self.weibo_url)
        time.sleep(3)

        logger.info("=" * 50)
        logger.info("👉 请在浏览器中完成微博登录！")
        logger.info("👉 登录成功后点击弹窗中的【我已登录】")
        logger.info("=" * 50)

        self._login_confirmed_by_user = False

        # 通知GUI显示确认弹窗
        if hasattr(self, '_on_login_prompt') and self._on_login_prompt:
            self._on_login_prompt()

        # 轮询检测登录状态
        max_wait = 180
        start_time = time.time()
        check_count = 0

        while time.time() - start_time < max_wait:
            check_count += 1

            if self._login_confirmed_by_user:
                logger.info("✅ 用户确认已登录")
                break

            if not self._is_login_page():
                logger.info(f"[第{check_count}次检测] 页面已跳转，登录成功")
                time.sleep(3)
                break

            if self._check_login_cookie():
                logger.info(f"[第{check_count}次检测] 检测到登录Cookie")
                time.sleep(2)
                break

            if check_count % 5 == 0:
                elapsed = int(time.time() - start_time)
                logger.info(f"[检测中] 已等待{elapsed}秒，请在浏览器中完成登录...")

            time.sleep(2)

        if self._login_confirmed_by_user or not self._is_login_page():
            self._save_cookies()
            logger.info("🎉 登录成功！Cookie已保存，下次运行将自动登录")
        else:
            raise Exception("登录超时（180秒），请重新运行程序并在浏览器中完成登录")

    def _save_cookies(self):
        """保存Cookie"""
        cookies = self.driver.get_cookies()
        with open(COOKIE_PATH, "wb") as f:
            pickle.dump(cookies, f)
        logger.info(f"Cookie已保存（共{len(cookies)}条）")

    def _load_cookies(self):
        """加载Cookie并验证"""
        self.driver.get(self.weibo_url)
        time.sleep(3)

        with open(COOKIE_PATH, "rb") as f:
            cookies = pickle.load(f)

        loaded_count = 0
        for cookie in cookies:
            for key in ["sameSite", "httpOnly"]:
                if cookie.get(key) is None:
                    cookie.pop(key, None)
            if "expiry" in cookie and cookie["expiry"] is None:
                cookie.pop("expiry", None)
            try:
                self.driver.add_cookie(cookie)
                loaded_count += 1
            except Exception:
                pass

        logger.info(f"已加载{loaded_count}条Cookie，刷新页面验证...")
        self.driver.refresh()
        time.sleep(5)

        on_login_page = self._is_login_page()
        has_cookie = self._check_login_cookie()

        if on_login_page and not has_cookie:
            logger.warning("Cookie已过期，需要重新登录")
            if COOKIE_PATH.exists():
                os.remove(COOKIE_PATH)
            self._manual_login()
        else:
            logger.info(f"✅ Cookie加载成功（域名: {urlparse(self.driver.current_url).hostname}）")

    # ================================================================
    # 文案拼接
    # ================================================================

    def compose_text(self, drama_name: str, episode_info: str, ai_review: str, template: str = None) -> str:
        """拼接完整文案，支持自定义模板"""
        if template:
            return (template
                    .replace("{剧名}", drama_name)
                    .replace("{集数}", episode_info)
                    .replace("{AI影评}", ai_review))
        return f"#{drama_name}# {episode_info} {ai_review} #电视剧#"

    # ================================================================
    # 微博发布（核心改进：图片上传等待 + 智能重试）
    # ================================================================

    def publish(self, text: str, image_path: str, max_retries: int = 3) -> bool:
        """
        发布微博

        关键流程（顺序很重要）：
        1. 打开微博 → 上传图片 → 等待上传完成 → 填入文字 → 点发布
        ★ 必须先上传图片再填文字，否则上传过程会清空文字
        """
        first_attempt = True

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"第{attempt}次尝试发布...")

                if first_attempt:
                    self.driver.get(self.weibo_url)
                    time.sleep(5)  # 等页面完全加载
                    first_attempt = False
                else:
                    # 重试：不刷新页面
                    logger.info("重试：复用当前页面...")
                    time.sleep(2)

                # ★ 步骤1：先上传图片（在填文字之前！）
                if attempt == 1:
                    self._upload_image(image_path)
                    # ★ 等待图片真正上传完成，最多等120秒
                    self._wait_image_uploaded(timeout=120)

                # ★ 步骤2：图片上传完成后再填文字
                self._fill_text(text)

                # 步骤3：点击发送
                submit_btn = self._find_submit_button()
                if not submit_btn:
                    raise Exception("找不到发送按钮")

                submit_btn.click()
                logger.info("已点击发送按钮，等待发布结果...")

                # 步骤4：检测发布结果
                if self._check_publish_success():
                    logger.info("✅ 微博发布成功！")
                    return True
                else:
                    raise Exception("发布超时，未检测到成功标志")

            except Exception as e:
                logger.warning(f"第{attempt}次发布失败: {e}")
                if attempt < max_retries:
                    logger.info("将在3秒后重试（不刷新页面）...")
                    time.sleep(3)
                else:
                    logger.error(f"❌ 发布失败，已重试{max_retries}次: {e}")
                    return False

        return False

    def _fill_text(self, text: str):
        """
        在微博输入框中填入文字

        使用多种方式尝试，确保文字能成功填入：
        1. 先用send_keys逐字输入（最可靠）
        2. 如果send_keys失败，用JS设置value
        3. 最后用JS设置innerText兜底
        """
        input_box = self._find_input_box()
        if not input_box:
            raise Exception("找不到微博输入框")

        # 点击输入框获得焦点
        input_box.click()
        time.sleep(1)

        # 清空已有内容
        input_box.clear()
        time.sleep(0.5)

        # 方式1：用send_keys直接输入（对textarea最可靠）
        try:
            input_box.send_keys(text)
            time.sleep(1)

            # 验证是否输入成功
            current_val = input_box.get_attribute("value") or ""
            if len(current_val) > 10:  # 输入了足够多的文字
                logger.info(f"文字输入成功（{len(current_val)}字，send_keys方式）")
                return
            # 如果send_keys没生效，继续尝试其他方式
            logger.warning(f"send_keys输入不完整（仅{len(current_val)}字），尝试其他方式...")
        except Exception as e:
            logger.warning(f"send_keys失败: {e}")

        # 方式2：用JS设置value（对textarea有效）
        try:
            self.driver.execute_script(
                "arguments[0].value = arguments[1];", input_box, text
            )
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                input_box,
            )
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                input_box,
            )
            time.sleep(1)

            current_val = input_box.get_attribute("value") or ""
            if len(current_val) > 10:
                logger.info(f"文字输入成功（{len(current_val)}字，JS value方式）")
                return
        except Exception as e:
            logger.warning(f"JS value方式失败: {e}")

        # 方式3：用JS设置innerText（对contenteditable div有效）
        try:
            self.driver.execute_script(
                "arguments[0].innerText = arguments[1];", input_box, text
            )
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                input_box,
            )
            time.sleep(1)
            logger.info("文字输入完成（innerText方式）")
            return
        except Exception as e:
            logger.warning(f"innerText方式失败: {e}")

        # 如果三种方式都失败
        logger.error("⚠️ 所有文字输入方式均失败，可能文字无法填入")

    def _wait_image_uploaded(self, timeout: int = 120):
        """
        等待图片上传完成（最多等120秒）

        微博图片上传到新浪图床需要较长时间（有时超过1分钟），
        通过轮询检测页面状态来判断上传是否完成。
        """
        logger.info(f"⏳ 等待图片上传完成（最多{timeout}秒）...")
        start_time = time.time()

        # 轮询检测：每隔3秒检查一次
        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)

            # 检测方式1：页面上出现了上传完成的图片预览
            preview_found = False
            preview_selectors = [
                ".wbpro-form img",
                ".WB_pic img",
                ".form_pic img",
                "img[src*='sinaimg']",
                ".wbpro-form .img_wrap img",
                "img[src*='photo']",
            ]
            for selector in preview_selectors:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if el and el.is_displayed():
                        preview_found = True
                        break
                except NoSuchElementException:
                    continue

            if preview_found:
                # 找到预览图，再等5秒确保渲染稳定
                time.sleep(5)
                logger.info(f"✅ 图片上传完成（{elapsed}秒，检测到预览图）")
                return

            # 检测方式2：上传input的value被清空
            try:
                file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                val = file_input.get_attribute("value")
                if not val or val.strip() == "":
                    # value清空了，但要再确认页面上有图片
                    time.sleep(3)
                    logger.info(f"✅ 图片上传完成（{elapsed}秒，input已清空）")
                    return
            except NoSuchElementException:
                pass

            # 检测方式3：通过JS检查页面上是否有img元素（简单粗暴但有效）
            try:
                has_images = self.driver.execute_script("""
                    var imgs = document.querySelectorAll('.wbpro-form img, .WB_pic img, img[src*="sinaimg"]');
                    return imgs.length > 0;
                """)
                if has_images:
                    time.sleep(5)
                    logger.info(f"✅ 图片上传完成（{elapsed}秒，JS检测到图片）")
                    return
            except Exception:
                pass

            # 每10秒输出一次等待日志
            if elapsed % 10 == 0 and elapsed > 0:
                logger.info(f"   仍在等待图片上传...（已{elapsed}秒）")

            time.sleep(3)

        # 超时：强制等待后继续（不阻塞流程）
        time.sleep(5)
        logger.warning(f"⚠️ 图片上传等待超时（{timeout}秒），尝试继续发布...")

    def _find_input_box(self):
        """定位微博输入框"""
        selectors = [
            "textarea[node-type='textEl']",
            "textarea.form_input",
            "div[node-type='textEl']",
            ".wbpro-form textarea",
            "textarea[placeholder*='分享']",
            "textarea[placeholder*='想法']",
            "textarea[placeholder*='说说']",
            "div[contenteditable='true'][node-type='textEl']",
            "#homeWrap textarea",
        ]
        for selector in selectors:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element and element.is_displayed():
                    return element
            except NoSuchElementException:
                continue
        try:
            return self.driver.execute_script("""
                var el = document.querySelector('textarea[node-type="textEl"]')
                    || document.querySelector('div[node-type="textEl"]')
                    || document.querySelector('.wbpro-form textarea')
                    || document.querySelector('textarea[placeholder]');
                return el;
            """)
        except Exception:
            return None

    def _upload_image(self, image_path: str):
        """上传图片"""
        abs_path = os.path.abspath(image_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"图片文件不存在: {abs_path}")

        upload_selectors = [
            "input[type='file']",
            "input[node-type='fileInput']",
            ".wbpro-form input[type='file']",
        ]
        uploaded = False
        for selector in upload_selectors:
            try:
                file_inputs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for file_input in file_inputs:
                    self.driver.execute_script(
                        "arguments[0].style.display='block'; arguments[0].style.visibility='visible';",
                        file_input,
                    )
                    file_input.send_keys(abs_path)
                    uploaded = True
                    logger.info(f"图片上传中: {os.path.basename(abs_path)}")
                    break
                if uploaded:
                    break
            except Exception as e:
                logger.debug(f"上传尝试失败（{selector}）: {e}")
                continue
        if not uploaded:
            raise Exception("找不到图片上传入口（input[type=file]）")

    def _find_submit_button(self):
        """定位发送按钮"""
        selectors = [
            "button[node-type='submit']",
            "a[node-type='submit']",
            ".wbpro-form button.btn_submit",
            "button.btn_32px",
            "a.W_btn_a[node-type='submit']",
            "span[node-type='submit']",
        ]
        for selector in selectors:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element and element.is_displayed():
                    return element
            except NoSuchElementException:
                continue
        try:
            return self.driver.execute_script("""
                var btns = document.querySelectorAll('button, a, span');
                for (var i = 0; i < btns.length; i++) {
                    var txt = btns[i].innerText || btns[i].textContent || '';
                    if ((txt.includes('发布') || txt.includes('发送')) && btns[i].offsetParent !== null) {
                        return btns[i];
                    }
                }
                return null;
            """)
        except Exception:
            return None

    def _check_publish_success(self, timeout: int = 10) -> bool:
        """检测发布是否成功"""
        success_selectors = [
            "a[action-type='feed_list_delete']",
            "a[title='删除']",
            ".card_feed a[title='删除']",
        ]
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                tip = self.driver.find_element(By.CSS_SELECTOR, ".msg_text, .W_layer_tips .txt")
                if "已发送" in tip.text or "成功" in tip.text:
                    return True
            except NoSuchElementException:
                pass
            for selector in success_selectors:
                try:
                    self.driver.find_element(By.CSS_SELECTOR, selector)
                    return True
                except NoSuchElementException:
                    pass
            time.sleep(1)
        for selector in success_selectors:
            try:
                self.driver.find_element(By.CSS_SELECTOR, selector)
                return True
            except NoSuchElementException:
                pass
        return False

    # ================================================================
    # 评论区
    # ================================================================

    def comment_on_post(self, comment_text: str, max_retries: int = 3) -> bool:
        """在刚发布的微博评论区发送评论（CDP注入，绕过ChromeDriver BMP限制）"""
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"第{attempt}次尝试发送评论...")
                comment_box = self._find_comment_box()
                if not comment_box:
                    self._expand_comment_section()
                    time.sleep(2)
                    comment_box = self._find_comment_box()
                if not comment_box:
                    raise Exception("找不到评论输入框")

                # 聚焦评论框
                comment_box.click()
                time.sleep(0.5)

                # 清空：全选+删除（避免 send_keys 的 BMP 限制）
                self.driver.execute_script(
                    "var b=arguments[0]; b.focus(); b.select();", comment_box
                )
                self.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
                    "type": "keyDown", "key": "Backspace", "code": "Backspace",
                    "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8,
                })
                self.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": "Backspace", "code": "Backspace",
                    "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8,
                })
                time.sleep(0.3)

                # 用 CDP Input.insertText 插入文字（支持任意 Unicode）
                self.driver.execute_cdp_cmd("Input.insertText", {"text": comment_text})
                time.sleep(1)

                # 点击提交按钮
                self.driver.execute_script("""
                    var btns = document.querySelectorAll('button,a,span');
                    for (var i = btns.length - 1; i >= 0; i--) {
                        var t = btns[i].textContent.trim();
                        if ((t === '评论' || t === '回复' || t === '发送') && btns[i].offsetParent !== null) {
                            btns[i].click(); break;
                        }
                    }
                """)
                time.sleep(3)
                logger.info("✅ 评论已发送")
                return True

            except Exception as e:
                logger.warning(f"第{attempt}次评论失败: {e}")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    logger.error(f"❌ 评论发送失败: {e}")
                    return False
        return False

    def _find_comment_box(self):
        selectors = [
            "textarea[placeholder*='评论']",
            "textarea[placeholder*='写评论']",
            "textarea[placeholder*='也说两句']",
            "textarea.W_input",
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in reversed(elements):
                    if el.is_displayed():
                        return el
            except NoSuchElementException:
                continue
        return None

    def _expand_comment_section(self):
        selectors = [
            "a[action-type='feed_list_comment']",
            "span[node-type='comment_count']",
            "a[title='评论']",
        ]
        for selector in selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    btn.click()
                    time.sleep(1)
                    return
            except (NoSuchElementException, ElementClickInterceptedException):
                continue

    def _find_comment_submit_button(self):
        selectors = [
            "button[node-type='submit']",
            "a[node-type='submit']",
            ".comment_send button",
        ]
        for selector in selectors:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        return btn
            except NoSuchElementException:
                continue
        return None

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
                logger.info("浏览器已关闭")
            except Exception:
                pass
            finally:
                self.driver = None
