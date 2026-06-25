"""
YLFile v4.3
Selenium + Chrome + PyQt5 + Live Table
"""
__version__ = "4.3"

import sys, os, csv, json, time, logging, threading
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox, QPlainTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QFormLayout, QRadioButton, QButtonGroup,
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

import requests as req_lib
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 常量 & 配置
# ============================================================
# PyInstaller打包后 __file__ 指向临时目录，需用 exe 所在目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
MEMORY_FILE = BASE_DIR / "memory.json"
COOKIE_FILE = BASE_DIR / "cookie.pkl"
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "api_base": "https://api.deepseek.com",
            "api_key": "",
            "model": "deepseek-v4-flash",
            "default_interval": 5,
            "max_retries": 3,
            "weibo_url": "https://weibo.com",
            "weibo_userid": "",
        }


def load_memory():
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"last_fields": {}, "posted_dramas": []}


def save_memory(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


# ============================================================
# 日志
# ============================================================
class LogSig(QObject):
    msg = pyqtSignal(str)
    fill = pyqtSignal(dict)
    pub_done = pyqtSignal()


log_sig = LogSig()


class GuiLogH(logging.Handler):
    def emit(self, r):
        log_sig.msg.emit(self.format(r))


def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter(fmt, "%H:%M:%S"))
    root.addHandler(h)
    h2 = logging.FileHandler(BASE_DIR / "log.txt", encoding="utf-8")
    h2.setLevel(logging.DEBUG)
    h2.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(h2)
    h3 = GuiLogH()
    h3.setLevel(logging.INFO)
    h3.setFormatter(logging.Formatter(fmt, "%H:%M:%S"))
    root.addHandler(h3)


logger = logging.getLogger(__name__)


# ============================================================
# 下载 & 工具函数
# ============================================================
def download_poster(url, name):
    h = {"Referer": "https://movie.douban.com/", "User-Agent": "Mozilla/5.0 Chrome/120"}
    ext = ".jpg"
    if ".png" in url.lower():
        ext = ".png"
    elif ".webp" in url.lower():
        ext = ".webp"
    fp = TEMP_DIR / f"{name}_{int(time.time() * 1000)}{ext}"
    r = req_lib.get(url, headers=h, timeout=30, stream=True, verify=False)
    r.raise_for_status()
    with open(fp, "wb") as f:
        for c in r.iter_content(8192):
            f.write(c)
    if os.path.getsize(fp) < 1024:
        os.remove(fp)
        raise Exception("download fail")
    if str(fp).lower().endswith(".webp"):
        try:
            from PIL import Image
            img = Image.open(fp)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            jpg = fp.with_suffix(".jpg")
            img.save(jpg, format="JPEG", quality=90)
            fp.unlink()
            fp = jpg
        except Exception:
            pass
    return str(fp)


def cleanup_temp(d=None):
    for f in TEMP_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in (".jpg", ".png", ".webp"):
            try:
                if d is None or d in f.name:
                    f.unlink()
            except Exception:
                pass


# ============================================================
# AI 影评生成
# ============================================================
from openai import OpenAI


def generate_review(drama, original="", year="", api_config=None):
    cfg = api_config or load_config()
    base = cfg.get("api_base", "")
    key = cfg.get("api_key", "")
    model = cfg.get("model", "deepseek-v4-flash")
    if not key:
        raise Exception("请填写 API Key")
    client = OpenAI(api_key=key, base_url=base)
    # 从 config 加载提示词，支持变量替换
    cfg_all = load_config()
    default_prompt = (
        '你是微博影视博主，给《{剧名} (original: {原名}) ({年份})》写一条推荐文案。\n'
        '严格要求：\n'
        '1. 100字左右，口语化，带3个emoji\n'
        '2. 不要说“刚看完”“刚追完”“刚刷完”开头\n'
        '3. 不要提具体集数，不要说“看到第几集”\n'
        '4. 不要说“太上头了”“不够看”“追不够”“根本停不下来”\n'
        '5. 不要用“安利”“种草”“必看”这类营销味重的词\n'
        '6. 不要用“谁懂啊”“家人们”“绝绝子”“救命”“姐妹们”等夸张网络用语\n'
        '7. 可以从角色、剧情、演技、配乐、画面、氛围等角度切入\n'
        '8. 开头要多样化，可以用提问、感叹、描述场景、聊角色等方式\n'
        '9. 语气自然、人性化，像朋友之间聊天一样推荐，不要太正式也不要太夸张\n'
        '10. 不加任何话题标签，只输出正文\n\n'
        '直接输出正文，不要前缀、标题、引号。'
    )
    tpl = cfg_all.get('ai_prompt', default_prompt)
    prompt = (tpl
              .replace('{剧名}', drama)
              .replace('{原名}', original or '')
              .replace('{年份}', year or ''))
    logger.info(f'AI请求: drama={drama}, original={original}, year={year}, model={model}')
    # 重试3次，逐步降低temperature
    temps = [0.9, 0.7, 0.5]
    for attempt, temp in enumerate(temps, 1):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=temp,
            )
            # 详细记录AI原始返回内容，便于排查截断问题
            raw_content = r.choices[0].message.content
            finish_reason = r.choices[0].finish_reason
            usage = r.usage
            logger.info(f"AI原始返回 (第{attempt}次):")
            logger.info(f"  finish_reason={finish_reason}")
            logger.info(f"  usage: prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}")
            logger.info(f"  原始内容长度: {len(raw_content) if raw_content else 0} 字符")
            logger.info(f"  原始完整内容: {raw_content}")

            if raw_content and raw_content.strip():
                content = raw_content.strip()
                if finish_reason == "length":
                    logger.warning(f"AI返回被截断(finish_reason=length)! max_tokens=500可能不够")
                if len(content) < 50:
                    logger.warning(f"AI第{attempt}次返回不完整({len(content)}字): {content[:30]}...")
                    if attempt < len(temps):
                        time.sleep(2)
                    continue
                logger.info(f"AI返回成功 (第{attempt}次): {content[:50]}...")
                return content
            logger.warning(f"AI第{attempt}次返回为空 (drama={drama})")
        except Exception as e:
            logger.warning(f"AI第{attempt}次调用异常 (drama={drama}): {e}")
            if attempt < len(temps):
                time.sleep(2)
    raise Exception(f"AI 3次重试均返回不完整，请检查网络或API设置 (drama={drama})")


# ============================================================
# 文案格式化
# ============================================================
def _format_episodes(season, eps):
    """生成集数文本。
    规则：
    - 集数空：见评
    - 集数为数字如39：全39集见评
    - 集数含/如2/39：更至第2集见评
    - 季数有值：1-{季数}季见评（优先）
    """
    eps = eps.strip()
    season = (season or "").strip()

    if season:
        try:
            season_num = int(season)
            return f"👇👇👇1-{season_num}季见评👇👇👇"
        except ValueError:
            pass

    if not eps:
        return "👇👇👇见评👇👇👇"

    if "/" in eps:
        parts = eps.split("/")
        try:
            current = int(parts[0].strip())
            return f"👇👇👇更至第{current}集见评👇👇👇"
        except ValueError:
            pass

    return f"👇👇👇全{eps}集见评👇👇👇"


def format_text(drama, orig, year, alias, season, dtype, eps, review, tag,
                template=None, eps_format=None, season_format=None):
    """使用模板拼接文案，{集数}和{季数}输出原始值"""
    if template:
        tag_name = (tag or "电视剧").strip()
        result = template
        result = result.replace("{剧名}", drama)
        result = result.replace("{季数}", season or "")
        result = result.replace("{集数}", eps or "")
        result = result.replace("{AI影评}", review)
        result = result.replace("{原名}", orig or "")
        result = result.replace("{年份}", year or "")
        result = result.replace("{又名}", alias or "")
        result = result.replace("{类型}", dtype or "")
        result = result.replace("{标签}", tag_name)
        return result
    # 兼容无模板的旧逻辑
    lines = []
    hdr = f"#{drama}#"
    if orig:
        hdr += f" {orig}"
    if year:
        hdr += f" {year}"
    lines.append(hdr)
    if alias:
        lines.append(f"又名：{alias}")
    if dtype:
        lines.append(dtype)
    if eps or season:
        ep_text = _format_episodes(season, eps)
        if ep_text:
            lines.append(ep_text)
    lines.append(review)
    tag_name = (tag or "电视剧").strip()
    lines.append(f"#{tag_name}#")
    return "\n".join(lines)


# ============================================================
# Selenium 驱动
# ============================================================
class WeiboDriver:
    def __init__(self, url="https://weibo.com"):
        self.url = url
        self.driver = None

    def start(self):
        logger.info("[调试] WeiboDriver.start() 开始")
        logger.info("[调试] 正在初始化Chrome驱动...")
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        try:
            self.driver = webdriver.Chrome(options=options)
            logger.info(f"[调试] Chrome驱动初始化完成, session_id={self.driver.session_id}")
        except Exception as e:
            logger.error(f"[调试] Chrome驱动初始化失败: {e}")
            raise
        logger.info("[调试] 执行反检测脚本...")
        try:
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
            )
            logger.info("[调试] 反检测脚本执行成功")
        except Exception as e:
            logger.warning(f"[调试] 反检测脚本执行失败: {e}")
        if COOKIE_FILE.exists():
            logger.info("[调试] 发现cookie文件，加载cookies...")
            self._load_cookies()
        else:
            logger.info("[调试] 无cookie文件，需要首次登录...")
            self._first_login()
        logger.info("[调试] 验证登录状态...")
        self._verify()
        logger.info("[调试] WeiboDriver.start() 完成")

    def _has_compose(self):
        try:
            self.driver.find_element(
                By.CSS_SELECTOR,
                'textarea[node-type="textEl"], .wbpro-form textarea, textarea[placeholder]',
            )
            return True
        except NoSuchElementException:
            pass
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'button[node-type="submit"]')
            return True
        except NoSuchElementException:
            pass
        return False

    def _verify(self):
        logger.info("[调试] _verify(): 打开微博首页验证登录...")
        self.driver.get(self.url)
        logger.info("[调试] _verify(): 等待5秒...")
        time.sleep(5)
        if self._has_compose():
            logger.info("[调试] _verify(): 检测到编辑器，登录成功")
            self._save()
            return
        has_sub = any(c["name"] == "SUB" for c in self.driver.get_cookies())
        if has_sub:
            logger.info("[调试] _verify(): 有SUB cookie，刷新页面...")
            self.driver.refresh()
            time.sleep(5)
            if self._has_compose():
                self._save()
                return
        logger.info("[调试] _verify(): 未登录，需要手动登录")
        self._first_login()

    def _first_login(self):
        self.driver.get(self.url)
        time.sleep(3)
        logger.info("=== 请在Chrome中登录微博（5分钟超时） ===")
        for i in range(150):
            time.sleep(2)
            if self._has_compose():
                time.sleep(3)
                break
            if any(c["name"] == "SUB" for c in self.driver.get_cookies()):
                self.driver.get(self.url)
                time.sleep(5)
                if self._has_compose():
                    break
            if i % 10 == 0:
                logger.info(f"等待登录中... ({i * 2}秒)")
        self._save()
        if self._has_compose():
            logger.info("登录成功！")
        else:
            logger.warning("登录可能失败")

    def _check_relogin(self):
        if self._has_compose():
            return False
        if any(c["name"] == "SUB" for c in self.driver.get_cookies()):
            self.driver.get(self.url)
            time.sleep(5)
            if self._has_compose():
                return False
        logger.info("需要重新登录...")
        self._first_login()
        return True

    def _save(self):
        import pickle
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(self.driver.get_cookies(), f)

    def _load_cookies(self):
        import pickle
        self.driver.get(self.url)
        time.sleep(3)
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
        for c in cookies:
            for k in ["sameSite", "httpOnly"]:
                if c.get(k) is None:
                    c.pop(k, None)
            if "expiry" in c and c["expiry"] is None:
                c.pop("expiry", None)
            try:
                self.driver.add_cookie(c)
            except Exception:
                pass
        self.driver.refresh()
        time.sleep(5)

    def publish(self, text, img_path, retries=3):
        for att in range(1, retries + 1):
            try:
                logger.info(f"[调试] publish() 第{att}次尝试")
                logger.info(f"[调试] 检查登录状态...")
                self._check_relogin()
                logger.info(f"[调试] 打开微博首页...")
                self.driver.get(self.url)
                logger.info(f"[调试] 等待页面加载 (6秒)...")
                time.sleep(6)
                logger.info(f"[调试] 注入文案到编辑器...")
                esc = json.dumps(text)
                self.driver.execute_script(
                    'var b=document.querySelector(\'textarea[node-type="textEl"]\')'
                    "||document.querySelector('.wbpro-form textarea')"
                    '||document.querySelector(\'textarea[placeholder]\');'
                    "if(b){b.focus();b.value=" + esc + ";"
                    "b.dispatchEvent(new Event('input',{bubbles:true}));"
                    "b.dispatchEvent(new Event('change',{bubbles:true}));}"
                )
                time.sleep(2)
                fi = None
                for s in ["input[type='file']", "input[node-type='fileInput']"]:
                    try:
                        fi = self.driver.find_element(By.CSS_SELECTOR, s)
                        break
                    except NoSuchElementException:
                        pass
                if fi:
                    import shutil, tempfile
                    ap = os.path.join(tempfile.gettempdir(), f"ylf_{int(time.time() * 1000)}.jpg")
                    shutil.copy2(img_path, ap)
                    fi.send_keys(ap)
                    logger.info(f"[调试] 图片上传中... (文件={ap})")
                    self._wait_upload(180)
                    try:
                        os.remove(ap)
                    except Exception:
                        pass
                else:
                    logger.warning("[调试] 未找到文件上传input，跳过图片上传")
                logger.info("[调试] 查找发布按钮...")
                btn = self._find_pub_btn()
                if not btn:
                    raise Exception("找不到发布按钮")
                logger.info(f"[调试] 点击发布按钮: {btn.tag_name} {btn.text[:20] if btn.text else ''}")
                btn.click()
                self._save()
                logger.info("已点击发布")
                if self._detect_ok(20):
                    logger.info("发布成功！")
                    return True
                raise Exception("发布检测未通过")
            except Exception as e:
                logger.warning(f"第{att}次: {e}")
                if att < retries:
                    time.sleep(3)
        return False

    def _wait_upload(self, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            e = int(time.time() - t0)
            try:
                for img in self.driver.find_elements(By.CSS_SELECTOR, "img"):
                    src = img.get_attribute("src") or ""
                    if "sinaimg" in src and img.is_displayed():
                        nw = self.driver.execute_script("return arguments[0].naturalWidth", img)
                        if nw and nw > 0:
                            logger.info(f"图片上传完成 ({e}秒)")
                            time.sleep(8)
                            return
            except Exception:
                pass
            if e > 0 and e % 15 == 0:
                logger.info(f"  等待上传... ({e}秒)")
            time.sleep(3)

    def _find_pub_btn(self):
        for s in ["button[node-type='submit']", "a[node-type='submit']"]:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, s)
                if el.is_displayed():
                    return el
            except NoSuchElementException:
                pass
        return self.driver.execute_script(
            "var b=document.querySelectorAll('button,a,span');"
            "for(var i=0;i<b.length;i++){var t=b[i].innerText||'';"
            "if((t.includes('发布')||t.includes('发送'))&&b[i].offsetParent!==null)return b[i];}"
            "return null;"
        )

    def _detect_ok(self, timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                b = self.driver.find_element(
                    By.CSS_SELECTOR,
                    'textarea[node-type="textEl"],.wbpro-form textarea',
                )
                v = b.get_attribute("value") or ""
                if not v.strip():
                    time.sleep(3)
                    return True
            except NoSuchElementException:
                pass
            time.sleep(1)
        return False

    def comment(self, text, uid="", retries=3):
        for att in range(1, retries + 1):
            try:
                url = f"https://weibo.com/u/{uid}" if uid else self.url
                logger.info(f"发评论: {url}")
                self.driver.get(url)
                time.sleep(5)
                btns = self.driver.execute_script(
                    "var r=[];var els=document.querySelectorAll('a,span');"
                    "for(var i=0;i<els.length;i++){var t=(els[i].innerText||'').trim();"
                    "if(t==='评论'&&els[i].offsetParent!==null)r.push(els[i]);}return r;"
                )
                if btns:
                    btns[0].click()
                    time.sleep(3)
                cbox = None
                for s in [
                    "textarea[placeholder*='评论']",
                    "textarea[placeholder*='写评论']",
                    "textarea[placeholder*='也说两句']",
                ]:
                    try:
                        els = self.driver.find_elements(By.CSS_SELECTOR, s)
                        for el in reversed(els):
                            if el.is_displayed():
                                cbox = el
                                break
                        if cbox:
                            break
                    except NoSuchElementException:
                        pass
                if not cbox:
                    raise Exception("找不到评论框")
                cbox.click()
                time.sleep(1)
                # 用 CDP 插入文字，绕过 ChromeDriver BMP 限制
                self.driver.execute_script(
                    "var b=arguments[0]; b.focus(); b.select();", cbox
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
                self.driver.execute_cdp_cmd("Input.insertText", {"text": text})
                time.sleep(1)
                sent = self.driver.execute_script(
                    "var b=arguments[0];var p=b.parentElement;"
                    'for(var i=0;i<10&&p;i++){var btns=p.querySelectorAll(\'button,a[node-type="submit"]\');'
                    "for(var j=0;j<btns.length;j++){var t=(btns[j].innerText||'').trim();"
                    "if((t==='评论'||t==='回复'||t==='发送')&&btns[j].offsetParent!==null)"
                    "{btns[j].click();return true;}}p=p.parentElement;}return false;",
                    cbox,
                )
                if not sent:
                    self.driver.execute_script(
                        'var btns=document.querySelectorAll(\'button[node-type="submit"]\');'
                        "for(var i=0;i<btns.length;i++){if(btns[i].offsetParent!==null&&"
                        "btns[i].getBoundingClientRect().top>300){btns[i].click();break;}}"
                    )
                time.sleep(3)
                self._save()
                logger.info(f"评论已发送: {text[:30]}")
                return True
            except Exception as e:
                logger.warning(f"评论失败({att}): {e}")
                if att < retries:
                    time.sleep(3)
        return False

    def is_alive(self):
        """检查浏览器会话是否仍然连接"""
        if not self.driver:
            return False
        try:
            self.driver.title
            return True
        except Exception:
            return False

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# ============================================================
# Worker: 单次发布（供手动和自动发布共用）
# ============================================================
def do_publish(gui, fields, cfg=None):
    """执行单次发布流程，返回 (success, is_fatal)。
    is_fatal=True 表示不可恢复的错误（如浏览器模块缺失），不应重试。
    使用 gui.shared_driver 复用浏览器会话。
    """
    if cfg is None:
        cfg = load_config()
    api = gui.get_api()

    drama = fields["drama"]
    poster = fields.get("poster", "")

    # 字段验证
    if not drama:
        logger.error("剧名为空，跳过")
        log_sig.pub_done.emit()
        return False, False
    if not poster:
        logger.error(f"{drama} 海报URL为空，跳过")
        log_sig.pub_done.emit()
        return False, False
    if not api.get("api_key"):
        logger.error("API Key 未填写")
        return False, False

    logger.info(f"AI影评: {drama} (原名={fields.get('original','')}, 年份={fields.get('year','')})")
    try:
        review = generate_review(drama, fields.get("original", ""), fields.get("year", ""), api)
    except Exception as e:
        logger.error(f"AI影评生成失败: {drama} - {e}")
        # AI失败也通知监听器跳到下一条，避免反复重试同一条
        log_sig.pub_done.emit()
        return False, False
    logger.info(f"AI影评: {review}")

    # 根据是否有季数选择单季/多季模板
    season_val = fields.get("season", "").strip()
    if season_val and hasattr(gui, 'inp_post_tpl_multi'):
        post_tpl = gui.inp_post_tpl_multi.toPlainText().strip()
    else:
        post_tpl = gui.inp_post_tpl.toPlainText().strip() if hasattr(gui, 'inp_post_tpl') else None
    text = format_text(
        drama, fields.get("original", ""), fields.get("year", ""),
        fields.get("alias", ""), season_val, fields.get("type", ""),
        fields.get("episodes", ""), review, fields.get("tag", ""),
        template=post_tpl,
    )
    logger.info(f"文案:\n{text}")

    logger.info(f"[调试] 准备下载海报: {fields['poster'][:80]}...")
    try:
        img = download_poster(fields["poster"], drama)
        logger.info(f"[调试] 海报下载完成: {img}")
    except Exception as e:
        logger.error(f"[调试] 海报下载失败: {e}")
        log_sig.pub_done.emit()
        return False, False

    # 检查并创建/复用 driver
    logger.info("[调试] 准备启动浏览器...")
    try:
        driver = gui.get_or_create_driver()
    except Exception as e:
        logger.error(f"[调试] 浏览器启动异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, True
    if driver is None:
        logger.error("[调试] 浏览器启动失败，get_or_create_driver返回None")
        return False, True
    logger.info(f"[调试] 浏览器就绪，准备发布 (driver.alive={driver.is_alive()})")

    try:
        ok = driver.publish(text, img, cfg.get("max_retries", 3))
        if ok:
            time.sleep(5)
            uid = cfg.get("weibo_userid", "")
            # 评论模板：支持所有变量 + {链接}
            def _fmt_comment(tpl, link):
                r = tpl.replace("{链接}", link or "")
                r = r.replace("{剧名}", fields.get("drama", ""))
                r = r.replace("{原名}", fields.get("original", ""))
                r = r.replace("{年份}", fields.get("year", ""))
                r = r.replace("{又名}", fields.get("alias", ""))
                r = r.replace("{类型}", fields.get("type", ""))
                r = r.replace("{季数}", fields.get("season", ""))
                r = r.replace("{集数}", fields.get("episodes", ""))
                r = r.replace("{AI影评}", fields.get("review", ""))
                r = r.replace("{标签}", fields.get("tag", ""))
                return r
            if fields.get("pan"):
                quark_tpl = gui.inp_comment_quark_tpl.text().strip() if hasattr(gui, 'inp_comment_quark_tpl') else "K👉{链接}"
                driver.comment(_fmt_comment(quark_tpl, fields['pan']), uid)
            if fields.get("baidu"):
                baidu_tpl = gui.inp_comment_baidu_tpl.text().strip() if hasattr(gui, 'inp_comment_baidu_tpl') else "D👉{链接}"
                driver.comment(_fmt_comment(baidu_tpl, fields['baidu']), uid)
            logger.info(f"已发布: {drama}")
            # 保存到 memory
            mem = load_memory()
            key = f"{drama}|{fields.get('original', '')}"
            if key not in mem.get("posted_dramas", []):
                mem.setdefault("posted_dramas", []).append(key)
            mem["last_fields"] = fields.copy()
            save_memory(mem)
            # 检查浏览器是否仍然连接
            if not driver.is_alive():
                gui.cleanup_driver()
                logger.warning("浏览器已关闭，请重新点击一键发布或自动发布")
                gui.set_status("浏览器已关闭，请重新发布")
            # 通知实时监听器
            log_sig.pub_done.emit()
            return True, False
        else:
            logger.error(f"发布失败: {drama}")
            # 检查是否浏览器被关闭导致的失败
            if not driver.is_alive():
                gui.cleanup_driver()
                logger.warning("浏览器已关闭，请重新点击一键发布或自动发布")
                gui.set_status("浏览器已关闭，请重新发布")
            return False, False
    finally:
        cleanup_temp(drama)


# ============================================================
# Worker: 手动一键发布
# ============================================================
class OneClickWorker(threading.Thread):
    def __init__(self, gui):
        super().__init__(daemon=True)
        self.gui = gui

    def run(self):
        try:
            self.gui.set_status("发布中...")
            self.gui.set_buttons_enabled(False)
            f = self.gui.get_fields()
            if not f["drama"]:
                logger.error("剧名为空")
                return
            if not f["poster"]:
                logger.error("无海报URL")
                return
            ok, _fatal = do_publish(self.gui, f)
            if ok:
                self.gui.set_status(f"已发布: {f['drama']}")
            else:
                self.gui.set_status(f"发布失败: {f['drama']}")
        except Exception as e:
            logger.error(f"异常: {e}")
            self.gui.set_status("发生异常，请查看日志")
        finally:
            self.gui.set_buttons_enabled(True)


# ============================================================
# Worker: 自动发布（定时器循环）
# ============================================================
class AutoPublishWorker(threading.Thread):
    def __init__(self, gui, interval_sec):
        super().__init__(daemon=True)
        self.gui = gui
        self.interval = interval_sec

    def run(self):
        cfg = load_config()
        count = 0
        MAX_AUTO_RETRIES = 3  # 发布失败后立即重试次数
        try:
            self.gui.set_status("自动发布中...")
            self.gui.btn_auto.setText("停止发布")

            while not self.gui.auto_stop_flag:
                f = self.gui.get_fields()

                # 检测必要字段：剧名、海报URL、标签
                missing = []
                if not f["drama"]:
                    missing.append("剧名")
                if not f["poster"]:
                    missing.append("海报URL")
                if not self.gui.inp_tag.text().strip():
                    missing.append("标签")
                if missing:
                    logger.info(f"必要字段未填写: {', '.join(missing)}，1分钟后重新检测...")
                    self.gui.set_status(f"等待填写: {', '.join(missing)}")
                    for _ in range(60):
                        if self.gui.auto_stop_flag:
                            return
                        time.sleep(1)
                    continue

                count += 1
                logger.info(f"--- 自动发布第{count}条: {f['drama']} ---")
                self.gui.set_status(f"自动发布 第{count}条: {f['drama']}")

                # 发布：失败后立即重试，最多MAX_AUTO_RETRIES次
                ok = False
                fatal = False
                for attempt in range(1, MAX_AUTO_RETRIES + 1):
                    ok, fatal = do_publish(self.gui, f, cfg=cfg)
                    if ok:
                        self.gui.set_status(f"已发布: {f['drama']}")
                        break
                    if fatal:
                        logger.error(f"遇到不可恢复的错误，停止自动发布")
                        self.gui.set_status("❌ 浏览器启动失败，请检查后重启")
                        break
                    logger.warning(f"发布失败 (第{attempt}/{MAX_AUTO_RETRIES}次): {f['drama']}")
                    if attempt < MAX_AUTO_RETRIES and not self.gui.auto_stop_flag:
                        logger.info(f"立即重试... (第{attempt + 1}次)")
                        self.gui.set_status(f"发布失败，重试第{attempt + 1}次: {f['drama']}")
                        time.sleep(3)  # 重试前短暂等待3秒

                if fatal:
                    break

                if not ok:
                    logger.error(f"发布{MAX_AUTO_RETRIES}次均失败，跳过: {f['drama']}")
                    self.gui.set_status(f"{MAX_AUTO_RETRIES}次失败，跳过: {f['drama']}")
                    # 失败跳过，不等待间隔，直接处理下一条
                    continue

                if self.gui.auto_stop_flag:
                    break

                # 发布成功，等待间隔时间后处理下一条
                mins = self.interval // 60
                logger.info(f"等待{mins}分钟后下一条...")
                for _ in range(self.interval):
                    if self.gui.auto_stop_flag:
                        break
                    time.sleep(1)

        except Exception as e:
            logger.error(f"自动发布异常: {e}")
            self.gui.set_status("自动发布异常")
        finally:
            self.gui.set_buttons_enabled(True)
            self.gui.btn_auto.setText("自动发布")
            logger.info(f"自动发布结束，共{count}条")


# ============================================================
# Worker: 实时监听（读取数据填入GUI，等待发布完成后读下一行）
# ============================================================
class LiveTableWorker(threading.Thread):
    def __init__(self, gui):
        super().__init__(daemon=True)
        self.gui = gui
        self._wait_event = threading.Event()
        self.POLL_INTERVAL = 180  # 3分钟轮询一次

    def run(self):
        try:
            logger.info("实时监听启动")
            self.gui.set_status("实时监听已启动，等待数据...")

            while not self.gui.stop_flag:
                # 读取数据源
                pending = self._get_pending_tasks()

                if pending:
                    row_num, task = pending[0]
                    self._fill_gui(task)
                    self.gui.current_row_num = row_num
                    self.gui.set_status(f"已加载 第{row_num}行: {task.get('drama', '')}")
                    logger.info(f"已填入第{row_num}行: {task.get('drama', '')}")

                    # 等待发布完成（pub_done 信号触发）
                    self._wait_event.clear()
                    self._wait_event.wait(timeout=600)
                    if self.gui.stop_flag:
                        break
                    # 发布完成，回到循环顶部读取下一条
                else:
                    # 无待处理数据，轮询等待新数据
                    logger.info(f"无新数据，{self.POLL_INTERVAL // 60}分钟后重新检查...")
                    self.gui.set_status(f"无新数据，{self.POLL_INTERVAL // 60}分钟后重新检查...")
                    for _ in range(self.POLL_INTERVAL):
                        if self.gui.stop_flag:
                            return
                        time.sleep(1)

        except Exception as e:
            logger.error(f"监听异常: {e}")
            self.gui.set_status("发生异常")
        finally:
            self.gui.btn_live.setText("开启实时监听")
            self.gui.btn_live.setEnabled(True)

    def _get_pending_tasks(self):
        """读取数据源，返回未发布的待处理任务列表"""
        all_tasks = self.gui._read_current_source()
        if not all_tasks:
            return []
        mem = load_memory()
        published = set(mem.get("posted_dramas", []))
        start_row = self.gui.get_start_row()
        pending = []
        for idx, t in enumerate(all_tasks):
            row_num = idx + 2  # 第1行是表头
            if row_num < start_row:
                continue
            key = f"{t.get('drama', '')}|{t.get('original', '')}"
            if key not in published:
                pending.append((row_num, t))
        return pending

    def _fill_gui(self, row):
        """通过信号在主线程填入GUI"""
        log_sig.fill.emit(row)


# ============================================================
# 主界面
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YLFile 微博发布工具")
        self.setGeometry(80, 80, 1060, 680)
        self.stop_flag = False
        self.auto_stop_flag = False
        self.memory = load_memory()
        self.config = load_config()
        self.shared_driver = None
        self.live_worker = None
        self.auto_worker = None
        self.current_row_num = 0

        FONT = "Microsoft YaHei"
        FS = 12

        self.setStyleSheet(f"""
            QMainWindow {{ background: #f0f2f5; }}
            QGroupBox {{ font-family: {FONT}; font-weight: bold; font-size: 14px; border: 1px solid #ddd;
                         border-radius: 6px; margin-top: 8px; padding-top: 14px; background: white; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #333; }}
            QLineEdit {{ padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-family: {FONT}; font-size: {FS}px; min-height: 24px; }}
            QLineEdit:focus {{ border: 1px solid #4a90d9; }}
            QPushButton {{ padding: 7px 18px; border-radius: 4px; font-family: {FONT}; font-size: {FS}px; font-weight: bold; min-height: 26px; }}
            QPushButton#pub {{ background: #3498db; color: white; }}
            QPushButton#pub:hover {{ background: #2980b9; }}
            QPushButton#auto {{ background: #e67e22; color: white; }}
            QPushButton#auto:hover {{ background: #d35400; }}
            QPushButton#live {{ background: #8e44ad; color: white; }}
            QPushButton#live:hover {{ background: #7d3c98; }}
            QPushButton#save {{ background: #27ae60; color: white; }}
            QPushButton#save:hover {{ background: #219a52; }}
            QPushButton#tpl {{ background: #6c757d; color: white; }}
            QPushButton#tpl:hover {{ background: #5a6268; }}
            QPushButton:disabled {{ background: #bbb; color: #888; }}
            QSpinBox {{ padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-family: {FONT}; font-size: {FS}px; min-height: 24px; }}
            QLabel {{ font-family: {FONT}; font-size: {FS}px; color: #333; }}
            QGroupBox QLabel {{ font-weight: normal; }}
            QRadioButton {{ font-family: Microsoft YaHei; font-size: 13px; font-weight: bold; }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QMessageBox {{ font-family: Microsoft YaHei; font-size: 12px; min-width: 250px; max-width: 400px; }}
            QMessageBox QLabel {{ font-family: Microsoft YaHei; font-size: 12px; }}
            QMessageBox QPushButton {{ font-family: Microsoft YaHei; font-size: 12px; padding: 5px 16px; min-width: 60px; border: 1px solid #aaa; border-radius: 4px; background: #f0f0f0; }}
            QMessageBox QPushButton:hover {{ background: #ddd; }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(10, 8, 10, 8)
        ml.setSpacing(6)

        # ===== 上半部分：发布内容 + 模板设置 + API设置&日志 =====
        top = QHBoxLayout()
        top.setSpacing(10)

        # 左：发布内容
        lb = QGroupBox("发布内容")
        lb.setFixedWidth(353)
        lf = QFormLayout()
        lf.setSpacing(5)
        lf.setLabelAlignment(Qt.AlignRight)

        self.inp_drama = QLineEdit()
        self.inp_drama.setPlaceholderText("必填 - 如：狂飙")
        lf.addRow("剧名 *:", self.inp_drama)

        self.inp_original = QLineEdit()
        self.inp_original.setPlaceholderText("可选")
        lf.addRow("原名:", self.inp_original)

        self.inp_year = QLineEdit()
        self.inp_year.setPlaceholderText("如 2023")
        self.inp_year.setMaximumWidth(120)
        lf.addRow("年份:", self.inp_year)

        self.inp_alias = QLineEdit()
        self.inp_alias.setPlaceholderText("可选")
        lf.addRow("又名:", self.inp_alias)

        self.inp_type = QLineEdit()
        self.inp_type.setPlaceholderText("如：剧情/犯罪/爱情")
        lf.addRow("类型:", self.inp_type)

        self.inp_season = QLineEdit()
        self.inp_season.setPlaceholderText("可选")
        self.inp_season.setMaximumWidth(120)
        lf.addRow("季数:", self.inp_season)

        self.inp_episodes = QLineEdit()
        self.inp_episodes.setPlaceholderText("如：39 或 2/39")
        self.inp_episodes.setMaximumWidth(150)
        lf.addRow("集数:", self.inp_episodes)

        self.inp_poster = QLineEdit()
        self.inp_poster.setPlaceholderText("必填 - 豆瓣图片链接")
        lf.addRow("海报URL *:", self.inp_poster)

        self.inp_pan = QLineEdit()
        self.inp_pan.setPlaceholderText("夸克网盘链接")
        lf.addRow("夸克链接:", self.inp_pan)

        self.inp_baidu = QLineEdit()
        self.inp_baidu.setPlaceholderText("可选")
        lf.addRow("百度链接:", self.inp_baidu)

        self.inp_tag = QLineEdit()
        self.inp_tag.setPlaceholderText("默认：电视剧")
        self.inp_tag.setMaximumWidth(120)
        lf.addRow("标签 *:", self.inp_tag)

        lb.setLayout(lf)
        top.addWidget(lb, stretch=2)

        # ===== 模板设置（常显示） =====
        tpl_group = QGroupBox("模板设置")
        tpl_group.setFixedWidth(353)
        tpl_layout = QFormLayout()
        tpl_layout.setSpacing(3)

        # 正文模板（单季）
        default_single = (
            "#{剧名}# {原名} {年份}\n"
            "又名：{又名}\n"
            "类型：{类型}\n"
            "👇👇👇全{集数}集见评👇👇👇\n"
            "{AI影评}#电视剧#"
        )
        self.inp_post_tpl = QPlainTextEdit(
            self.config.get("post_template", default_single)
        )
        self.inp_post_tpl.setPlaceholderText("单季模板")
        self.inp_post_tpl.setFixedHeight(100)
        self.inp_post_tpl.setStyleSheet("font-size:13px;")
        tpl_layout.addRow("正文(单季):", self.inp_post_tpl)

        # 正文模板（多季）
        default_multi = (
            "#{剧名}# {原名}\n"
            "又名：{又名}\n"
            "类型：{类型}\n"
            "👇👇👇1-{季数}季见评👇👇👇\n"
            "{AI影评}#电视剧#"
        )
        self.inp_post_tpl_multi = QPlainTextEdit(
            self.config.get("post_template_multi", default_multi)
        )
        self.inp_post_tpl_multi.setPlaceholderText("多季模板")
        self.inp_post_tpl_multi.setFixedHeight(100)
        self.inp_post_tpl_multi.setStyleSheet("font-size:13px;")
        tpl_layout.addRow("正文(多季):", self.inp_post_tpl_multi)

        # 统一变量提示
        lbl_var = QLabel("变量: {剧名} {集数} {季数} {AI影评} {原名} {年份} {又名} {类型} {标签}")
        lbl_var.setWordWrap(True)
        tpl_layout.addRow("", lbl_var)

        # 评论模板
        self.inp_comment_quark_tpl = QLineEdit(
            self.config.get("comment_quark_template", "K👉{链接}")
        )
        self.inp_comment_quark_tpl.setPlaceholderText("评论·夸克模板")
        tpl_layout.addRow("夸克:", self.inp_comment_quark_tpl)

        self.inp_comment_baidu_tpl = QLineEdit(
            self.config.get("comment_baidu_template", "D👉{链接}")
        )
        self.inp_comment_baidu_tpl.setPlaceholderText("评论·百度模板")
        tpl_layout.addRow("百度:", self.inp_comment_baidu_tpl)

        lbl_comment_var = QLabel("变量: {链接} {剧名} {原名} {年份} {又名} {类型} {季数} {集数} {AI影评} {标签}")
        lbl_comment_var.setWordWrap(True)
        tpl_layout.addRow("", lbl_comment_var)

        btn_tpl_row = QHBoxLayout()
        btn_restore_tpl = QPushButton("恢复默认")
        btn_restore_tpl.setObjectName("tpl")
        btn_restore_tpl.clicked.connect(self._restore_templates)
        btn_tpl_row.addWidget(btn_restore_tpl)
        btn_ai_prompt = QPushButton("AI提示词")
        btn_ai_prompt.setObjectName("tpl")
        btn_ai_prompt.clicked.connect(self._open_ai_prompt_dialog)
        btn_tpl_row.addWidget(btn_ai_prompt)
        btn_tpl_row.addStretch()
        tpl_layout.addRow("", btn_tpl_row)

        tpl_group.setLayout(tpl_layout)
        top.addWidget(tpl_group, stretch=1)

        # 右：API设置 + 日志
        right_stack = QVBoxLayout()
        right_stack.setSpacing(6)

        rb = QGroupBox("API设置")
        rb.setFixedWidth(353)
        rf = QFormLayout()
        rf.setSpacing(5)

        self.inp_api_base = QLineEdit(self.config.get("api_base", ""))
        self.inp_api_base.setPlaceholderText("API地址")
        rf.addRow("Base URL:", self.inp_api_base)

        self.inp_api_key = QLineEdit(self.config.get("api_key", ""))
        self.inp_api_key.setEchoMode(QLineEdit.Password)
        self.inp_api_key.setPlaceholderText("API密钥")
        rf.addRow("API Key:", self.inp_api_key)

        self.inp_api_model = QLineEdit(self.config.get("model", ""))
        self.inp_api_model.setPlaceholderText("模型名称")
        rf.addRow("模型:", self.inp_api_model)

        rb.setLayout(rf)
        right_stack.addWidget(rb)

        lg = QGroupBox("运行日志")
        lg.setFixedWidth(353)
        lgl = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
            "background:#1a1a2e;color:#e0e0e0;font-family:Consolas,Microsoft YaHei;font-size:10pt;"
            "border:1px solid #333;border-radius:4px;padding:4px;"
        )
        lgl.addWidget(self.log_area)
        lg.setLayout(lgl)
        right_stack.addWidget(lg, stretch=1)

        top.addLayout(right_stack, stretch=1)
        ml.addLayout(top, stretch=3)

        # ===== 按钮行 =====
        bl = QHBoxLayout()

        self.btn_pub = QPushButton("一键发布")
        self.btn_pub.setObjectName("pub")
        self.btn_pub.clicked.connect(self.on_pub)
        bl.addWidget(self.btn_pub)

        self.btn_auto = QPushButton("自动发布")
        self.btn_auto.setObjectName("auto")
        self.btn_auto.clicked.connect(self.on_auto)
        bl.addWidget(self.btn_auto)

        self.btn_live = QPushButton("开启实时监听")
        self.btn_live.setObjectName("live")
        self.btn_live.clicked.connect(self._toggle_live)
        bl.addWidget(self.btn_live)

        ml.addLayout(bl)

        # Tab order
        self.setTabOrder(self.inp_drama, self.inp_original)
        self.setTabOrder(self.inp_original, self.inp_year)
        self.setTabOrder(self.inp_year, self.inp_alias)
        self.setTabOrder(self.inp_alias, self.inp_type)
        self.setTabOrder(self.inp_type, self.inp_season)
        self.setTabOrder(self.inp_season, self.inp_episodes)
        self.setTabOrder(self.inp_episodes, self.inp_poster)
        self.setTabOrder(self.inp_poster, self.inp_pan)
        self.setTabOrder(self.inp_pan, self.inp_baidu)
        self.setTabOrder(self.inp_baidu, self.inp_tag)

        # ===== 数据源设置 =====
        ds_group = QGroupBox("数据源设置")
        ds_layout = QHBoxLayout()
        ds_layout.setSpacing(8)

        # 飞书表格
        fs_box = QGroupBox()
        fs_box_layout = QVBoxLayout()
        self.radio_feishu = QRadioButton("飞书表格")
        self.radio_feishu.setObjectName("radio_source")
        fs_box_layout.addWidget(self.radio_feishu)
        fs_form = QFormLayout()
        fs_form.setSpacing(4)
        self.inp_feishu_token = QLineEdit()
        self.inp_feishu_token.setPlaceholderText("表格Token")
        fs_form.addRow("Token:", self.inp_feishu_token)
        self.inp_feishu_sheet = QLineEdit("Sheet1")
        self.inp_feishu_sheet.setPlaceholderText("工作表名")
        fs_form.addRow("工作表:", self.inp_feishu_sheet)
        self.inp_feishu_appid = QLineEdit()
        self.inp_feishu_appid.setPlaceholderText("App ID")
        fs_form.addRow("App ID:", self.inp_feishu_appid)
        self.inp_feishu_secret = QLineEdit()
        self.inp_feishu_secret.setEchoMode(QLineEdit.Password)
        self.inp_feishu_secret.setPlaceholderText("App Secret")
        fs_form.addRow("Secret:", self.inp_feishu_secret)
        fs_box_layout.addLayout(fs_form)
        fs_box.setLayout(fs_box_layout)
        ds_layout.addWidget(fs_box, stretch=1)

        # Google Sheets
        gs_box = QGroupBox()
        gs_box_layout = QVBoxLayout()
        self.radio_google = QRadioButton("Google Sheets")
        self.radio_google.setObjectName("radio_source")
        gs_box_layout.addWidget(self.radio_google)
        gs_form = QFormLayout()
        gs_form.setSpacing(4)
        self.inp_gsheet_id = QLineEdit()
        self.inp_gsheet_id.setPlaceholderText("表格ID")
        gs_form.addRow("表格ID:", self.inp_gsheet_id)
        self.inp_gsheet_key = QLineEdit()
        self.inp_gsheet_key.setPlaceholderText("API Key")
        gs_form.addRow("API Key:", self.inp_gsheet_key)
        self.inp_gsheet_range = QLineEdit("Sheet1!A:K")
        self.inp_gsheet_range.setPlaceholderText("读取范围")
        gs_form.addRow("范围:", self.inp_gsheet_range)
        gs_box_layout.addLayout(gs_form)
        gs_box.setLayout(gs_box_layout)
        ds_layout.addWidget(gs_box, stretch=1)

        # 本地CSV + 设置
        csv_box = QGroupBox()
        csv_box_layout = QVBoxLayout()
        self.radio_local = QRadioButton("本地CSV")
        self.radio_local.setObjectName("radio_source")
        self.radio_local.setChecked(True)
        csv_box_layout.addWidget(self.radio_local)
        csv_form = QVBoxLayout()

        csv_row = QHBoxLayout()
        self.inp_csv = QLineEdit()
        self.inp_csv.setPlaceholderText("CSV文件路径")
        csv_row.addWidget(self.inp_csv, stretch=1)
        self.btn_browse = QPushButton("选择")
        self.btn_browse.setObjectName("tpl")
        self.btn_browse.clicked.connect(self._browse)
        csv_row.addWidget(self.btn_browse)
        csv_form.addLayout(csv_row)

        settings = QFormLayout()
        settings.setSpacing(4)
        r_int = QHBoxLayout()
        self.spn_int = QSpinBox()
        self.spn_int.setRange(1, 60)
        self.spn_int.setValue(self.config.get("default_interval", 5))
        self.spn_int.setMaximumWidth(45)
        r_int.addWidget(self.spn_int)
        r_int.addWidget(QLabel("分钟"))
        r_int.addStretch()
        settings.addRow("间隔:", r_int)
        self.inp_uid = QLineEdit(self.config.get("weibo_userid", ""))
        self.inp_uid.setPlaceholderText("评论用用户ID")
        settings.addRow("用户ID:", self.inp_uid)
        r_row = QHBoxLayout()
        self.inp_start_row = QLineEdit(str(self.config.get("start_row", 2)))
        self.inp_start_row.setMaximumWidth(55)
        self.inp_start_row.setPlaceholderText("2")
        r_row.addWidget(self.inp_start_row)
        r_row.addStretch()
        settings.addRow("起始行:", r_row)
        csv_form.addLayout(settings)

        btn_row = QHBoxLayout()
        self.btn_tpl = QPushButton("下载CSV模板")
        self.btn_tpl.setObjectName("tpl")
        self.btn_tpl.clicked.connect(self._download_template)
        btn_row.addWidget(self.btn_tpl)
        self.btn_save_all = QPushButton("保存所有设置")
        self.btn_save_all.setObjectName("save")
        self.btn_save_all.clicked.connect(self._save_all)
        btn_row.addWidget(self.btn_save_all)
        csv_form.addLayout(btn_row)

        csv_box_layout.addLayout(csv_form)
        csv_box.setLayout(csv_box_layout)
        ds_layout.addWidget(csv_box, stretch=1)

        # Radio button 互斥组
        self.ds_btn_group = QButtonGroup(self)
        self.ds_btn_group.addButton(self.radio_feishu, 0)
        self.ds_btn_group.addButton(self.radio_google, 1)
        self.ds_btn_group.addButton(self.radio_local, 2)

        ds_group.setLayout(ds_layout)
        ml.addWidget(ds_group)

        # 状态栏
        self.lbl_st = QLabel("就绪")
        self.lbl_st.setStyleSheet("font-family:Microsoft YaHei;font-size:13px;color:#666;padding:4px;")
        ml.addWidget(self.lbl_st)

        # 信号连接
        log_sig.fill.connect(self._do_fill_gui)
        log_sig.pub_done.connect(self._on_pub_done)
        log_sig.msg.connect(self._add_log)

        # 恢复上次设置
        self._restore()

    # ----- 信号处理 -----
    def _add_log(self, m):
        self.log_area.append(m)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_pub_done(self):
        """发布成功信号 → 更新起始行 + 自动保存 + 通知监听器"""
        # 更新起始行
        if self.current_row_num > 0:
            self.set_start_row(self.current_row_num + 1)
            logger.info(f"起始行更新为: {self.current_row_num + 1}")
        # 自动保存所有设置（防止忘记保存导致配置丢失）
        try:
            self.config["api_base"] = self.inp_api_base.text().strip()
            self.config["api_key"] = self.inp_api_key.text().strip()
            self.config["model"] = self.inp_api_model.text().strip()
            self.config["weibo_userid"] = self.inp_uid.text().strip()
            self.config["csv_path"] = self.inp_csv.text().strip()
            self.config["selected_source"] = (
                "feishu" if self.radio_feishu.isChecked()
                else ("google" if self.radio_google.isChecked() else "local")
            )
            self.config["gsheet_id"] = self.inp_gsheet_id.text()
            self.config["gsheet_key"] = self.inp_gsheet_key.text()
            self.config["gsheet_range"] = self.inp_gsheet_range.text()
            self.config["feishu_token"] = self.inp_feishu_token.text()
            self.config["feishu_sheet"] = self.inp_feishu_sheet.text()
            self.config["feishu_appid"] = self.inp_feishu_appid.text()
            self.config["feishu_secret"] = self.inp_feishu_secret.text()
            self.config["default_interval"] = self.spn_int.value()
            self.config["start_row"] = self.get_start_row()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            logger.info("发布成功，已自动保存所有设置")
        except Exception as e:
            logger.warning(f"自动保存失败: {e}")
        # 通知监听器
        if self.live_worker and hasattr(self.live_worker, "_wait_event"):
            self.live_worker._wait_event.set()

    def _do_fill_gui(self, row):
        """主线程填入GUI字段"""
        def safe(k):
            return str(row.get(k) or "")
        self.inp_drama.setText(safe("drama"))
        self.inp_original.setText(safe("original"))
        self.inp_year.setText(safe("year"))
        self.inp_alias.setText(safe("alias"))
        self.inp_type.setText(safe("type"))
        self.inp_season.setText(safe("season"))
        self.inp_episodes.setText(safe("episodes"))
        self.inp_poster.setText(safe("poster"))
        self.inp_pan.setText(safe("pan"))
        self.inp_baidu.setText(safe("baidu"))
        self.inp_tag.setText(row.get("tag", "") or "电视剧")

    # ----- 状态 & 按钮 -----
    def set_status(self, t):
        self.lbl_st.setText(t)

    def set_buttons_enabled(self, ok):
        """ok=True: 所有按钮可用; ok=false: 禁用一键发布"""
        self.btn_pub.setEnabled(ok)

    # ----- 浏览器管理 -----
    def get_or_create_driver(self):
        """获取或创建共享的 Selenium driver"""
        if self.shared_driver and self.shared_driver.driver and self.shared_driver.is_alive():
            logger.info("[调试] 复用已有浏览器会话")
            return self.shared_driver
        # 创建新的 driver
        logger.info("[调试] 创建新的 WeiboDriver 实例...")
        try:
            cfg = load_config()
            self.shared_driver = WeiboDriver(cfg.get("weibo_url", "https://weibo.com"))
            self.shared_driver.start()
            logger.info("[调试] WeiboDriver.start() 调用成功")
            return self.shared_driver
        except Exception as e:
            logger.error(f"[调试] 浏览器启动失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.shared_driver = None
            return None

    def cleanup_driver(self):
        """清理共享 driver"""
        if self.shared_driver:
            try:
                self.shared_driver.close()
            except Exception:
                pass
            self.shared_driver = None

    # ----- 起始行管理 -----
    def get_start_row(self):
        """获取起始行数值"""
        try:
            return int(self.inp_start_row.text().strip())
        except (ValueError, AttributeError):
            return 2

    def set_start_row(self, row):
        """设置起始行数值"""
        self.inp_start_row.setText(str(row))

    # ----- 获取数据 -----
    def get_fields(self):
        """从GUI获取当前字段"""
        return {
            "drama": self.inp_drama.text().strip(),
            "original": self.inp_original.text().strip(),
            "year": self.inp_year.text().strip(),
            "alias": self.inp_alias.text().strip(),
            "type": self.inp_type.text().strip(),
            "season": self.inp_season.text().strip(),
            "episodes": self.inp_episodes.text().strip(),
            "poster": self.inp_poster.text().strip(),
            "pan": self.inp_pan.text().strip(),
            "baidu": self.inp_baidu.text().strip(),
            "tag": self.inp_tag.text().strip() or "电视剧",
        }

    def get_api(self):
        return {
            "api_base": self.inp_api_base.text().strip(),
            "api_key": self.inp_api_key.text().strip(),
            "model": self.inp_api_model.text().strip(),
        }

    def _is_dup(self, d, o):
        return f"{d}|{o}" in self.memory.get("posted_dramas", [])

    # ----- 按钮动作 -----
    def on_pub(self):
        """一键发布"""
        f = self.get_fields()
        if not f["drama"]:
            QMessageBox.warning(self, "提示", "请填写剧名")
            return
        if not f["poster"]:
            QMessageBox.warning(self, "提示", "请填写海报URL")
            return
        if self._is_dup(f["drama"], f["original"]):
            if (
                QMessageBox.question(
                    self, "重复", f"{f['drama']}已发布。再次发布？",
                    QMessageBox.Yes | QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
        self.stop_flag = False
        self.set_buttons_enabled(False)
        OneClickWorker(self).start()

    def on_auto(self):
        """自动发布（定时器循环一键发布）"""
        if self.auto_worker and self.auto_worker.is_alive():
            # 停止
            self.auto_stop_flag = True
            self.auto_worker = None
            self.set_status("停止自动发布...")
            logger.info("停止自动发布")
            return
        # 启动
        self.auto_stop_flag = False
        interval_sec = self.spn_int.value() * 60
        self.auto_worker = AutoPublishWorker(self, interval_sec)
        self.auto_worker.start()

    def _toggle_live(self):
        """开启/关闭实时监听"""
        if self.live_worker and self.live_worker.is_alive():
            self.stop_flag = True
            self.live_worker = None
            self.btn_live.setText("开启实时监听")
            self.btn_live.setEnabled(True)
            self.set_status("已停止")
            logger.info("停止实时监听")
            return
        self.stop_flag = False
        self.btn_live.setText("停止监听")
        self.live_worker = LiveTableWorker(self)
        self.live_worker.start()
        self.set_status("实时监听启动...")

    def closeEvent(self, event):
        """程序退出时清理资源"""
        self.stop_flag = True
        self.cleanup_driver()
        event.accept()

    # ----- 设置保存/恢复 -----
    def _restore_templates(self):
        """恢复模板为默认值"""
        try:
            self.inp_post_tpl.setPlainText(
                "#{剧名}# {原名} {年份}\n又名：{又名}\n类型：{类型}\n"
                "👇👇👇全{集数}集见评👇👇👇\n{AI影评}#电视剧#"
            )
            self.inp_post_tpl_multi.setPlainText(
                "#{剧名}# {原名}\n又名：{又名}\n类型：{类型}\n"
                "👇👇👇1-{季数}季见评👇👇👇\n{AI影评}#电视剧#"
            )
            self.inp_comment_quark_tpl.setText("K👉{链接}")
            self.inp_comment_baidu_tpl.setText("D👉{链接}")
            logger.info('模板已恢复默认，请点击[保存所有设置]生效')
        except Exception as e:
            logger.error(f"恢复模板失败: {e}")

    # ----- AI提示词弹窗 -----
    DEFAULT_AI_PROMPT = (
        '你是微博影视博主，给《{剧名} (original: {原名}) ({年份})》写一条推荐文案。\n'
        '严格要求：\n'
        '1. 100字左右，口语化，带3个emoji\n'
        '2. 不要说"刚看完""刚追完""刚刷完"开头\n'
        '3. 不要提具体集数，不要说"看到第几集"\n'
        '4. 不要说"太上头了""不够看""追不够""根本停不下来"\n'
        '5. 不要用"安利""种草""必看"这类营销味重的词\n'
        '6. 不要用"谁懂啊""家人们""绝绝子""救命""姐妹们"等夸张网络用语\n'
        '7. 可以从角色、剧情、演技、配乐、画面、氛围等角度切入\n'
        '8. 开头要多样化，可以用提问、感叹、描述场景、聊角色等方式\n'
        '9. 语气自然、人性化，像朋友之间聊天一样推荐，不要太正式也不要太夸张\n'
        '10. 不加任何话题标签，只输出正文\n\n'
        '直接输出正文，不要前缀、标题、引号。'
    )

    def _open_ai_prompt_dialog(self):
        """打开AI提示词编辑弹窗"""
        dlg = QMainWindow(self)
        dlg.setWindowTitle("AI影评提示词设置")
        dlg.setFixedSize(600, 500)
        dlg.setAttribute(Qt.WA_DeleteOnClose)

        central = QWidget()
        dlg.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        layout.addWidget(QLabel("提示词模板（变量: {剧名} {原名} {年份}）："))

        txt = QPlainTextEdit()
        txt.setPlainText(self.config.get("ai_prompt", self.DEFAULT_AI_PROMPT))
        txt.setStyleSheet("font-size:12px;")
        layout.addWidget(txt)

        btn_row = QHBoxLayout()

        def on_restore():
            txt.setPlainText(self.DEFAULT_AI_PROMPT)

        def on_confirm():
            self.config["ai_prompt"] = txt.toPlainText().strip()
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
                logger.info("AI提示词已保存")
            except Exception as e:
                logger.error(f"保存AI提示词失败: {e}")
            dlg.close()

        btn_default = QPushButton("恢复默认")
        btn_default.setObjectName("tpl")
        btn_default.clicked.connect(on_restore)
        btn_row.addWidget(btn_default)

        btn_row.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("save")
        btn_ok.clicked.connect(on_confirm)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)
        dlg.show()

    def _save_cfg(self):
        self.config["api_base"] = self.inp_api_base.text().strip()
        self.config["api_key"] = self.inp_api_key.text().strip()
        self.config["model"] = self.inp_api_model.text().strip()
        self.config["weibo_userid"] = self.inp_uid.text().strip()
        self.config["csv_path"] = self.inp_csv.text().strip()
        self.config["selected_source"] = (
            "feishu" if self.radio_feishu.isChecked()
            else ("google" if self.radio_google.isChecked() else "local")
        )
        self.config["gsheet_id"] = self.inp_gsheet_id.text().strip()
        self.config["gsheet_key"] = self.inp_gsheet_key.text().strip()
        self.config["gsheet_range"] = self.inp_gsheet_range.text().strip()
        self.config["feishu_token"] = self.inp_feishu_token.text().strip()
        self.config["feishu_sheet"] = self.inp_feishu_sheet.text().strip()
        self.config["feishu_appid"] = self.inp_feishu_appid.text().strip()
        self.config["feishu_secret"] = self.inp_feishu_secret.text().strip()
        self.config["start_row"] = self.get_start_row()
        self.config["post_template"] = self.inp_post_tpl.toPlainText().strip()
        self.config["post_template_multi"] = self.inp_post_tpl_multi.toPlainText().strip()
        self.config["comment_quark_template"] = self.inp_comment_quark_tpl.text().strip()
        self.config["comment_baidu_template"] = self.inp_comment_baidu_tpl.text().strip()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        logger.info("设置已保存")

    def _save_all(self):
        self.config["api_base"] = self.inp_api_base.text().strip()
        self.config["api_key"] = self.inp_api_key.text().strip()
        self.config["model"] = self.inp_api_model.text().strip()
        self.config["weibo_userid"] = self.inp_uid.text().strip()
        self.config["csv_path"] = self.inp_csv.text().strip()
        self.config["selected_source"] = (
            "feishu" if self.radio_feishu.isChecked()
            else ("google" if self.radio_google.isChecked() else "local")
        )
        self.config["gsheet_id"] = self.inp_gsheet_id.text()
        self.config["gsheet_key"] = self.inp_gsheet_key.text()
        self.config["gsheet_range"] = self.inp_gsheet_range.text()
        self.config["feishu_token"] = self.inp_feishu_token.text()
        self.config["feishu_sheet"] = self.inp_feishu_sheet.text()
        self.config["feishu_appid"] = self.inp_feishu_appid.text()
        self.config["feishu_secret"] = self.inp_feishu_secret.text()
        self.config["default_interval"] = self.spn_int.value()
        self.config["start_row"] = self.get_start_row()
        self.config["post_template"] = self.inp_post_tpl.toPlainText().strip()
        self.config["post_template_multi"] = self.inp_post_tpl_multi.toPlainText().strip()
        self.config["comment_quark_template"] = self.inp_comment_quark_tpl.text().strip()
        self.config["comment_baidu_template"] = self.inp_comment_baidu_tpl.text().strip()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        logger.info("所有设置已保存")
        QMessageBox.information(self, "保存成功", "所有设置已保存")

    def _restore(self):
        """恢复上次的输入和设置"""
        lf = self.memory.get("last_fields", {})
        field_map = [
            ("drama", self.inp_drama), ("original", self.inp_original),
            ("year", self.inp_year), ("alias", self.inp_alias),
            ("type", self.inp_type), ("season", self.inp_season),
            ("episodes", self.inp_episodes), ("poster", self.inp_poster),
            ("pan", self.inp_pan), ("baidu", self.inp_baidu), ("tag", self.inp_tag),
        ]
        for k, w in field_map:
            if lf.get(k):
                w.setText(lf[k])
        # 恢复数据源设置
        if self.config.get("csv_path"):
            self.inp_csv.setText(self.config["csv_path"])
        if self.config.get("gsheet_id"):
            self.inp_gsheet_id.setText(self.config["gsheet_id"])
        if self.config.get("gsheet_key"):
            self.inp_gsheet_key.setText(self.config["gsheet_key"])
        if self.config.get("gsheet_range"):
            self.inp_gsheet_range.setText(self.config["gsheet_range"])
        if self.config.get("feishu_token"):
            self.inp_feishu_token.setText(self.config["feishu_token"])
        if self.config.get("feishu_sheet"):
            self.inp_feishu_sheet.setText(self.config["feishu_sheet"])
        if self.config.get("feishu_appid"):
            self.inp_feishu_appid.setText(self.config["feishu_appid"])
        if self.config.get("feishu_secret"):
            self.inp_feishu_secret.setText(self.config["feishu_secret"])
        if self.config.get("start_row"):
            self.set_start_row(self.config["start_row"])
        sel = self.config.get("selected_source", "local")
        if sel == "feishu":
            self.radio_feishu.setChecked(True)
        elif sel == "google":
            self.radio_google.setChecked(True)
        else:
            self.radio_local.setChecked(True)
        if lf:
            logger.info(f"恢复上次输入: {lf.get('drama', '')}")

    # ----- 数据源浏览 -----
    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "CSV", "", "CSV (*.csv)")
        if p:
            self.inp_csv.setText(p)

    def _download_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "weibo_template.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["剧名", "原名", "年份", "又名", "类型", "季数", "集数", "海报URL", "夸克链接", "百度链接", "标签"])
            w.writerow(["狂飙", "The Knockout", "2023", "狂飙", "剧情", "", "39",
                         "https://img.doubanio.com/xxx.jpg", "https://pan.quark.cn/s/abc", "", "电视剧"])
        logger.info(f"模板已保存: {path}")
        QMessageBox.information(self, "成功", f"模板已保存到:\n{path}")

    # ----- 数据源读取 -----
    def _read_current_source(self):
        """根据 radio button 选择读取对应数据源"""
        if self.radio_feishu.isChecked():
            return self._read_feishu()
        elif self.radio_google.isChecked():
            return self._read_google_sheets()
        elif self.radio_local.isChecked():
            return self._read_local_csv()
        return []

    def _read_local_csv(self):
        source = self.inp_csv.text().strip()
        if not source or not os.path.exists(source):
            return []
        mapping = {
            "剧名": "drama", "原名": "original", "年份": "year", "又名": "alias",
            "类型": "type", "季数": "season", "集数": "episodes", "海报URL": "poster",
            "夸克链接": "pan", "百度链接": "baidu", "标签": "tag",
        }
        with open(source, "r", encoding="utf-8-sig") as f:
            raw = list(csv.DictReader(f))
        tasks = []
        for row in raw:
            d = {mapping.get(k, k): (v.strip() if v else "") for k, v in row.items()}
            if d.get("drama"):
                tasks.append(d)
        logger.info(f"本地CSV读取到{len(tasks)}条数据")
        return tasks

    def _read_google_sheets(self):
        sheet_id = self.inp_gsheet_id.text().strip()
        api_key = self.inp_gsheet_key.text().strip()
        rng = self.inp_gsheet_range.text().strip() or "Sheet1!A:K"
        if not sheet_id or not api_key:
            QMessageBox.warning(self, "提示", "请填写表格ID和API Key")
            return []
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}?key={api_key}"
        logger.info(f"读取Google Sheets: {sheet_id}")
        try:
            resp = req_lib.get(url, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Google API错误: {resp.status_code} {resp.text[:200]}")
                return []
            data = resp.json()
            values = data.get("values", [])
            if not values:
                logger.error("表格为空")
                return []
            headers = values[0]
            mapping = {
                "剧名": "drama", "原名": "original", "年份": "year", "又名": "alias",
                "类型": "type", "季数": "season", "集数": "episodes", "海报URL": "poster",
                "夸克链接": "pan", "百度链接": "baidu", "标签": "tag",
            }
            tasks = []
            for row in values[1:]:
                d = {}
                for i, h in enumerate(headers):
                    d[mapping.get(h, h)] = row[i].strip() if i < len(row) else ""
                if d.get("drama"):
                    tasks.append(d)
            logger.info(f"Google Sheets读取到{len(tasks)}条数据")
            return tasks
        except Exception as e:
            logger.error(f"Google Sheets读取失败: {e}")
            return []

    def _get_feishu_token(self, app_id, app_secret):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = req_lib.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("tenant_access_token")
        logger.error(f"飞书Token获取失败: {data}")
        return None

    def _get_feishu_sheet_id(self, token, access_token, sheet_name):
        url = f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{token}/sheets/query"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = req_lib.get(url, headers=headers, timeout=15)
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"查询工作表失败: {data}")
                return None
            sheets = data.get("data", {}).get("sheets", [])
            for s in sheets:
                title = s.get("title", "")
                sid = s.get("sheet_id", "")
                if title == sheet_name or title.lower() == sheet_name.lower():
                    logger.info(f"匹配到工作表: {title} -> {sid}")
                    return sid
            if sheets:
                first = sheets[0]
                sid = first.get("sheet_id", "")
                logger.info(f"未匹配到'{sheet_name}'，使用第一个: {first.get('title', '')} -> {sid}")
                return sid
            return None
        except Exception as e:
            logger.error(f"查询工作表失败: {e}")
            return None

    @staticmethod
    def _parse_feishu_cell(val):
        if val is None:
            return ""
        if isinstance(val, list):
            parts = []
            for item in val:
                if isinstance(item, dict):
                    parts.append(item.get("link", item.get("text", "")))
                else:
                    parts.append(str(item))
            return " ".join(parts).strip()
        if isinstance(val, dict):
            return val.get("link", val.get("text", str(val)))
        return str(val).strip()

    def _read_feishu(self):
        token = self.inp_feishu_token.text().strip()
        sheet_name = self.inp_feishu_sheet.text().strip() or "Sheet1"
        app_id = self.inp_feishu_appid.text().strip()
        app_secret = self.inp_feishu_secret.text().strip()
        if not token or not app_id or not app_secret:
            QMessageBox.warning(self, "提示", "请填写表格Token、App ID和App Secret")
            return []
        access_token = self._get_feishu_token(app_id, app_secret)
        if not access_token:
            return []
        sheet_id = self._get_feishu_sheet_id(token, access_token, sheet_name)
        if not sheet_id:
            logger.error(f"未找到工作表: {sheet_name}")
            return []
        url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values/{sheet_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        logger.info(f"读取飞书表格: {token} / {sheet_id}")
        try:
            resp = req_lib.get(url, headers=headers, timeout=30)
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"飞书API错误: {data}")
                return []
            values = data.get("data", {}).get("valueRange", {}).get("values", [])
            if not values:
                logger.error("表格为空")
                return []
            headers_row = values[0]
            mapping = {
                "剧名": "drama", "原名": "original", "年份": "year", "又名": "alias",
                "类型": "type", "季数": "season", "集数": "episodes", "海报URL": "poster",
                "夸克链接": "pan", "百度链接": "baidu", "标签": "tag",
            }
            tasks = []
            for row in values[1:]:
                d = {}
                for i, h in enumerate(headers_row):
                    val = row[i] if i < len(row) else None
                    d[mapping.get(h, h)] = self._parse_feishu_cell(val)
                if d.get("drama"):
                    tasks.append(d)
            logger.info(f"飞书表格读取到{len(tasks)}条数据")
            return tasks
        except Exception as e:
            logger.error(f"飞书读取失败: {e}")
            return []


# ============================================================
# 入口
# ============================================================
def main():
    setup_logging()
    logger.info(f"YLFile v{__version__} 启动")
    app = QApplication(sys.argv)
    w = MainWindow()

    # --- 自动更新检查（后台线程 + 信号回调到主线程） ---
    class _UpdateSignal(QObject):
        result_ready = pyqtSignal(object)

    _sig = _UpdateSignal()

    def _check():
        try:
            from updater import check_update
            result = check_update(__version__)
        except Exception as e:
            logger.warning(f"自动更新检查异常: {e}")
            result = None
        _sig.result_ready.emit(result)

    def _on_result(result):
        if result is None:
            return
        _, new_ver, download_url = result
        ret = QMessageBox.question(
            w, "发现新版本",
            f"发现新版本 v{new_ver}，是否更新？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            from updater import download_update, restart_app
            dest = Path(os.environ.get("TEMP", ".")) / "YLFile"
            dest.mkdir(exist_ok=True)
            new_exe = download_update(download_url, dest)
            if new_exe:
                QMessageBox.information(w, "更新完成", "新版本下载完成，点击确定将重启应用。")
                restart_app(new_exe)
            else:
                QMessageBox.warning(w, "更新失败", "下载失败，请稍后重试或手动下载。")

    _sig.result_ready.connect(_on_result)
    threading.Thread(target=_check, daemon=True).start()
    # --- 更新检查结束 ---

    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
