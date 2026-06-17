"""
YLFile v4.0
Selenium + Chrome + PyQt5 + Live Table
"""
import sys, os, csv, json, time, logging, threading
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox,
    QFileDialog, QMessageBox, QFrame, QGroupBox, QFormLayout,
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException

import requests as req_lib
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
MEMORY_FILE = BASE_DIR / "memory.json"
COOKIE_FILE = BASE_DIR / "cookie.pkl"
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {"api_base":"https://api.deepseek.com","api_key":"","model":"deepseek-v4-flash",
                    "default_interval":5,"max_retries":3,"weibo_url":"https://weibo.com","weibo_userid":""}

def load_memory():
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except: pass
    return {"last_fields":{},"posted_dramas":[]}

def save_memory(mem):
    with open(MEMORY_FILE,"w",encoding="utf-8") as f: json.dump(mem,f,ensure_ascii=False,indent=2)

# Logging
class LogSig(QObject):
    msg = pyqtSignal(str)
log_sig = LogSig()
class GuiLogH(logging.Handler):
    def emit(self,r): log_sig.msg.emit(self.format(r))
def setup_logging():
    fmt="%(asctime)s [%(levelname)s] %(message)s"
    root=logging.getLogger(); root.setLevel(logging.DEBUG); root.handlers.clear()
    h=logging.StreamHandler(sys.stdout); h.setLevel(logging.INFO); h.setFormatter(logging.Formatter(fmt,"%H:%M:%S")); root.addHandler(h)
    h2=logging.FileHandler(BASE_DIR/"log.txt",encoding="utf-8"); h2.setLevel(logging.DEBUG); h2.setFormatter(logging.Formatter(fmt,"%Y-%m-%d %H:%M:%S")); root.addHandler(h2)
    h3=GuiLogH(); h3.setLevel(logging.INFO); h3.setFormatter(logging.Formatter(fmt,"%H:%M:%S")); root.addHandler(h3)
logger=logging.getLogger(__name__)

# Download
def download_poster(url, name):
    h={"Referer":"https://movie.douban.com/","User-Agent":"Mozilla/5.0 Chrome/120"}
    ext=".jpg"
    if ".png" in url.lower(): ext=".png"
    elif ".webp" in url.lower(): ext=".webp"
    fp=TEMP_DIR/f"{name}_{int(time.time()*1000)}{ext}"
    r=req_lib.get(url,headers=h,timeout=30,stream=True,verify=False); r.raise_for_status()
    with open(fp,"wb") as f:
        for c in r.iter_content(8192): f.write(c)
    if os.path.getsize(fp)<1024: os.remove(fp); raise Exception("download fail")
    if str(fp).lower().endswith('.webp'):
        try:
            from PIL import Image
            img=Image.open(fp)
            if img.mode in('RGBA','P'): img=img.convert('RGB')
            jpg=fp.with_suffix('.jpg'); img.save(jpg,format='JPEG',quality=90); fp.unlink(); fp=jpg
        except: pass
    return str(fp)
def cleanup_temp(d=None):
    for f in TEMP_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in(".jpg",".png",".webp"):
            try:
                if d is None or d in f.name: f.unlink()
            except: pass

# AI
from openai import OpenAI
def generate_review(drama, original="", year="", api_config=None):
    cfg=api_config or load_config()
    base=cfg.get("api_base",""); key=cfg.get("api_key",""); model=cfg.get("model","deepseek-v4-flash")
    if not key: raise Exception("Fill API Key!")
    client=OpenAI(api_key=key,base_url=base)
    ctx=f"{drama}"
    if original: ctx+=f" (original: {original})"
    if year: ctx+=f" ({year})"
    prompt=(
        f"你是微博影视博主，给《{ctx}》写一条推荐文案。\n"
        "严格要求：\n"
        "1. 100字左右，口语化，带3个emoji\n"
        "2. 不要说“刚看完”“刚追完”“刚刷完”开头\n"
        "3. 不要提具体集数，不要说“看到第几集”\n"
        "4. 不要说“太上头了”“不够看”“追不够”“根本停不下来”\n"
        "5. 不要用“安利”“种草”“必看”这类营销味重的词\n"
        "6. 可以从角色、剧情、演技、配乐、画面、氛围等角度切入\n"
        "7. 开头要多样化，可以用提问、感叹、描述场景、聊角色等方式\n"
        "8. 语气像真人随手发的，不要太正式\n"
        "9. 不加任何话题标签，只输出正文\n\n"
        "直接输出正文，不要前缀、标题、引号。"
    )
    for _ in range(2):
        r=client.chat.completions.create(model=model,messages=[{"role":"user","content":prompt}],max_tokens=300,temperature=0.9)
        c=r.choices[0].message.content
        if c and c.strip(): return c.strip()
    raise Exception("AI empty, check API")

def _format_episodes(season, eps):
    """Generate episode text.
    Rules:
    - eps empty: no text
    - eps is number like 39: 全39集见评
    - eps contains / like 2/39: 更至第2集见评
    - season has number: 1-{season}季见评 (takes priority)
    """
    eps = eps.strip()
    season = (season or "").strip()

    # Multi-season takes priority
    if season:
        try:
            season_num = int(season)
            return f"👉👉👉1-{season_num}季见评👉👉👉"
        except ValueError:
            pass

    if not eps:
        return "👉👉👉见评👉👉👉"

    # eps contains /
    if "/" in eps:
        parts = eps.split("/")
        try:
            current = int(parts[0].strip())
            return f"👉👉👉更至第{current}集见评👉👉👉"
        except ValueError:
            pass

    # eps is a number
    return f"👉👉👉全{eps}集见评👉👉👉"



def format_text(drama, orig, year, alias, season, dtype, eps, review, tag):
    lines=[]
    hdr = f"#{drama}#"
    if orig: hdr += f" {orig}"
    if year: hdr += f" {year}"
    lines.append(hdr)
    if alias: lines.append(f"又名：{alias}")
    if dtype: lines.append(dtype)
    if eps or season:
        ep_text = _format_episodes(season, eps)
        if ep_text: lines.append(ep_text)
    lines.append(review)
    tag_name = (tag or "电视剧").strip()
    lines.append(f"#{tag_name}#")
    return "\n".join(lines)


# ============================================================
# Selenium Driver
# ============================================================
class WeiboDriver:
    def __init__(self, url="https://weibo.com"):
        self.url = url; self.driver = None

    def start(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        if COOKIE_FILE.exists(): self._load_cookies()
        else: self._first_login()
        self._verify()

    def _has_compose(self):
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'textarea[node-type="textEl"], .wbpro-form textarea, textarea[placeholder]')
            return True
        except: pass
        try:
            self.driver.find_element(By.CSS_SELECTOR, 'button[node-type="submit"]')
            return True
        except: pass
        return False

    def _verify(self):
        self.driver.get(self.url); time.sleep(5)
        if self._has_compose():
            logger.info("登录验证成功"); self._save(); return
        has_sub = any(c["name"] == "SUB" for c in self.driver.get_cookies())
        if has_sub:
            self.driver.refresh(); time.sleep(5)
            if self._has_compose(): self._save(); return
        logger.info("未登录"); self._first_login()

    def _first_login(self):
        self.driver.get(self.url); time.sleep(3)
        logger.info("=== 请在Chrome中登录微博（5分钟超时） ===")
        for i in range(150):
            time.sleep(2)
            if self._has_compose(): time.sleep(3); break
            if any(c["name"] == "SUB" for c in self.driver.get_cookies()):
                self.driver.get(self.url); time.sleep(5)
                if self._has_compose(): break
            if i % 10 == 0: logger.info(f"等待登录中... ({i*2}秒)")
        self._save()
        if self._has_compose(): logger.info("登录成功！")
        else: logger.warning("登录可能失败")

    def _check_relogin(self):
        if self._has_compose(): return False
        if any(c["name"] == "SUB" for c in self.driver.get_cookies()):
            self.driver.get(self.url); time.sleep(5)
            if self._has_compose(): return False
        logger.info("需要重新登录..."); self._first_login(); return True

    def _save(self):
        import pickle
        with open(COOKIE_FILE, "wb") as f: pickle.dump(self.driver.get_cookies(), f)

    def _load_cookies(self):
        import pickle
        self.driver.get(self.url); time.sleep(3)
        with open(COOKIE_FILE, "rb") as f: cookies = pickle.load(f)
        for c in cookies:
            for k in ["sameSite", "httpOnly"]:
                if c.get(k) is None: c.pop(k, None)
            if "expiry" in c and c["expiry"] is None: c.pop("expiry", None)
            try: self.driver.add_cookie(c)
            except: pass
        self.driver.refresh(); time.sleep(5)

    def publish(self, text, img_path, retries=3):
        for att in range(1, retries+1):
            try:
                logger.info(f"发布第{att}次尝试...")
                self._check_relogin()
                self.driver.get(self.url); time.sleep(6)
                import json as _j
                esc = _j.dumps(text)
                self.driver.execute_script(
                    'var b=document.querySelector(\'textarea[node-type="textEl"]\')'
                    '||document.querySelector(\'.wbpro-form textarea\')'
                    '||document.querySelector(\'textarea[placeholder]\');'
                    'if(b){b.focus();b.value='+esc+';'
                    'b.dispatchEvent(new Event(\'input\',{bubbles:true}));'
                    'b.dispatchEvent(new Event(\'change\',{bubbles:true}));}')
                time.sleep(2)
                fi = None
                for s in ["input[type='file']", "input[node-type='fileInput']"]:
                    try: fi = self.driver.find_element(By.CSS_SELECTOR, s); break
                    except: pass
                if fi:
                    import shutil, tempfile
                    ap = os.path.join(tempfile.gettempdir(), f"ylf_{int(time.time()*1000)}.jpg")
                    shutil.copy2(img_path, ap); fi.send_keys(ap)
                    logger.info("图片上传中..."); self._wait_upload(180)
                    try: os.remove(ap)
                    except: pass
                btn = self._find_pub_btn()
                if not btn: raise Exception("找不到发布按钮")
                btn.click(); self._save(); logger.info("已点击发布")
                if self._detect_ok(20): logger.info("发布成功！"); return True
                raise Exception("发布检测未通过")
            except Exception as e:
                logger.warning(f"第{att}次: {e}")
                if att < retries: time.sleep(3)
        return False

    def _wait_upload(self, timeout=180):
        t0 = time.time()
        while time.time()-t0 < timeout:
            e = int(time.time()-t0)
            try:
                for img in self.driver.find_elements(By.CSS_SELECTOR, "img"):
                    src = img.get_attribute("src") or ""
                    if "sinaimg" in src and img.is_displayed():
                        nw = self.driver.execute_script("return arguments[0].naturalWidth", img)
                        if nw and nw > 0: logger.info(f"图片上传完成 ({e}秒)"); time.sleep(8); return
            except: pass
            if e > 0 and e % 15 == 0: logger.info(f"  等待上传... ({e}秒)")
            time.sleep(3)

    def _find_pub_btn(self):
        for s in ["button[node-type='submit']", "a[node-type='submit']"]:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, s)
                if el.is_displayed(): return el
            except: pass
        return self.driver.execute_script(
            "var b=document.querySelectorAll('button,a,span');"
            "for(var i=0;i<b.length;i++){var t=b[i].innerText||'';"
            "if((t.includes('发布')||t.includes('发送'))&&b[i].offsetParent!==null)return b[i];}return null;")

    def _detect_ok(self, timeout=20):
        t0 = time.time()
        while time.time()-t0 < timeout:
            try:
                b = self.driver.find_element(By.CSS_SELECTOR, 'textarea[node-type="textEl"],.wbpro-form textarea')
                v = b.get_attribute("value") or ""
                if not v.strip(): time.sleep(3); return True
            except: pass
            time.sleep(1)
        return False

    def comment(self, text, uid="", retries=3):
        for att in range(1, retries+1):
            try:
                url = f"https://weibo.com/u/{uid}" if uid else self.url
                logger.info(f"发评论: {url}")
                self.driver.get(url); time.sleep(5)
                btns = self.driver.execute_script(
                    "var r=[];var els=document.querySelectorAll('a,span');"
                    "for(var i=0;i<els.length;i++){var t=(els[i].innerText||'').trim();"
                    "if(t==='评论'&&els[i].offsetParent!==null)r.push(els[i]);}return r;")
                if btns: btns[0].click(); time.sleep(3)
                cbox = None
                for s in ["textarea[placeholder*='评论']",
                           "textarea[placeholder*='写评论']",
                           "textarea[placeholder*='也说两句']"]:
                    try:
                        els = self.driver.find_elements(By.CSS_SELECTOR, s)
                        for el in reversed(els):
                            if el.is_displayed(): cbox = el; break
                        if cbox: break
                    except: pass
                if not cbox: raise Exception("找不到评论框")
                cbox.click(); time.sleep(1); cbox.clear()
                cbox.send_keys(text); time.sleep(1)
                sent = self.driver.execute_script(
                    "var b=arguments[0];var p=b.parentElement;"
                    "for(var i=0;i<10&&p;i++){var btns=p.querySelectorAll('button,a[node-type=\"submit\"]');"
                    "for(var j=0;j<btns.length;j++){var t=(btns[j].innerText||'').trim();"
                    "if((t==='评论'||t==='回复'||t==='发送')&&btns[j].offsetParent!==null)"
                    "{btns[j].click();return true;}}p=p.parentElement;}return false;", cbox)
                if not sent:
                    self.driver.execute_script(
                        "var btns=document.querySelectorAll('button[node-type=\"submit\"]');"
                        "for(var i=0;i<btns.length;i++){if(btns[i].offsetParent!==null&&"
                        "btns[i].getBoundingClientRect().top>300){btns[i].click();break;}}")
                time.sleep(3); self._save()
                logger.info(f"评论已发送: {text[:30]}"); return True
            except Exception as e:
                logger.warning(f"评论失败({att}): {e}")
                if att < retries: time.sleep(3)
        return False

    def close(self):
        if self.driver:
            try: self.driver.quit()
            except: pass
            self.driver = None

# ============================================================
# Workers
# ============================================================
class PublishWorker(threading.Thread):
    def __init__(self, gui, fields):
        super().__init__(daemon=True); self.gui=gui; self.f=fields
    def run(self):
        try:
            self.gui.set_status("发布中..."); self.gui.set_buttons(False)
            cfg=load_config(); api=self.gui.get_api()
            logger.info(f"AI影评: {self.f['drama']}...")
            review=generate_review(self.f['drama'],self.f.get('original',''),self.f.get('year',''),api)
            logger.info(f"AI影评: {review}")
            text=format_text(self.f['drama'],self.f.get('original',''),self.f.get('year',''),
                            self.f.get('alias',''),self.f.get('season',''),self.f.get('type',''),
                            self.f.get('episodes',''),review,self.f.get('tag',''))
            logger.info(f"文案:\n{text}")
            img=download_poster(self.f['poster'],self.f['drama'])
            driver=self.gui.shared_driver
            if driver is None or driver.driver is None:
                driver=WeiboDriver(cfg.get("weibo_url","https://weibo.com")); driver.start()
                self.gui.shared_driver=driver
            ok=driver.publish(text,img,cfg.get("max_retries",3))
            if ok:
                time.sleep(5); uid=cfg.get("weibo_userid","")
                for line in self.f.get("comment_lines",[]): driver.comment(line,uid)
                logger.info(f"已发布: {self.f['drama']}")
                self.gui.set_status(f"已发布: {self.f['drama']}")
                mem=load_memory(); key=f"{self.f['drama']}|{self.f.get('original','')}"
                if key not in mem.get("posted_dramas",[]): mem.setdefault("posted_dramas",[]).append(key)
                mem["last_fields"]=self.f.copy(); save_memory(mem)
            else:
                logger.error(f"发布失败: {self.f['drama']}")
                self.gui.set_status(f"发布失败: {self.f['drama']}")
            cleanup_temp(self.f['drama'])
        except Exception as e:
            logger.error(f"异常: {e}"); self.gui.set_status("发生异常，请查看日志")
        finally: self.gui.set_buttons(True)


class LiveTableWorker(threading.Thread):
    def __init__(self, gui, csv_path, interval):
        super().__init__(daemon=True); self.gui=gui; self.csv_path=csv_path; self.interval=interval
    def run(self):
        logger.info(f"实时表格启动 (间隔{self.interval}秒)")
        published=set(load_memory().get("posted_dramas",[]))
        start_row=getattr(self,'start_row',2)
        while not self.gui.stop_flag:
            try:
                real_path=self.gui._resolve_csv_path()
                if not real_path:
                    logger.warning("无法获取表格数据"); time.sleep(self.interval); continue
                with open(real_path,"r",encoding="utf-8-sig") as f:
                    rows=list(csv.DictReader(f))
                    for idx,row in enumerate(rows):
                        if idx+2 < start_row: continue
                        drama=row.get("剧名","").strip(); orig=row.get("原名","").strip()
                        key=f"{drama}|{orig}"
                        if not drama or key in published: continue
                        poster=row.get("海报URL","").strip()
                        if not poster: continue
                        logger.info(f"新声明: {drama}")
                        fields={"drama":drama,"original":orig,"year":row.get("年份","").strip(),
                               "alias":row.get("又名","").strip(),"season":row.get("季数","").strip(),
                               "type":row.get("类型","").strip(),"episodes":row.get("集数","").strip(),
                               "poster":poster,"pan":row.get("夸克链接","").strip(),
                               "baidu":row.get("百度链接","").strip(),
                               "tag":row.get("标签","").strip() or "电视剧","comment_lines":[]}
                        if fields["pan"]: fields["comment_lines"].append(f"夸：{fields['pan']}")
                        if fields["baidu"]: fields["comment_lines"].append(f"度：{fields['baidu']}")
                        pw=PublishWorker(self.gui,fields); pw.start(); pw.join()
                        published.add(key)
                        if self.gui.stop_flag: break
                        for _ in range(self.interval):
                            if self.gui.stop_flag: break; time.sleep(1)
            except Exception as e: logger.error(f"实时表格错误: {e}")
            for _ in range(self.interval):
                if self.gui.stop_flag: break; time.sleep(1)
        logger.info("实时表格已停止")

class BatchPublishWorker(threading.Thread):
    def __init__(self, gui, source, interval, start_row=2, is_wps=False):
        super().__init__(daemon=True)
        self.gui = gui; self.source = source; self.interval = interval
        self.start_row = start_row; self.is_wps = is_wps; self.tasks = []

    def _fill_gui(self, row):
        self.gui.root.after(0, lambda: self._do_fill(row))
    def _do_fill(self, row):
        self.gui.inp_drama.setText(row.get("\u5267\u540d","").strip())
        self.gui.inp_original.setText(row.get("\u539f\u540d","").strip())
        self.gui.inp_year.setText(row.get("\u5e74\u4efd","").strip())
        self.gui.inp_alias.setText(row.get("\u53c8\u540d","").strip())
        self.gui.inp_type.setText(row.get("\u7c7b\u578b","").strip())
        self.gui.inp_season.setText(row.get("\u5b63\u6570","").strip())
        self.gui.inp_episodes.setText(row.get("\u96c6\u6570","").strip())
        self.gui.inp_poster.setText(row.get("\u6d77\u62a5URL","").strip())
        self.gui.inp_pan.setText(row.get("\u5938\u514b\u94fe\u63a5","").strip())
        self.gui.inp_baidu.setText(row.get("\u767e\u5ea6\u94fe\u63a5","").strip())
        self.gui.inp_tag.setText(row.get("\u6807\u7b7e","").strip() or "\u7535\u89c6\u5267")
        self.gui.inp_drama.repaint()

    def _read_wps_table(self, driver):
        logger.info(f"\u6253\u5f00WPS\u94fe\u63a5: {self.source}")
        driver.get(self.source)
        time.sleep(10)
        js = """(function(){
            var tables=document.querySelectorAll('table');
            if(tables.length>0){
                var rows=[];var trs=tables[0].querySelectorAll('tr');
                for(var i=0;i<trs.length;i++){
                    var cells=trs[i].querySelectorAll('td,th');var row=[];
                    for(var j=0;j<cells.length;j++)row.push(cells[j].innerText.trim());
                    if(row.length>0)rows.push(row);
                }
                return JSON.stringify(rows);
            }
            var div=document.querySelector('[class*="table"],[class*="sheet"],[class*="grid"]');
            if(div){
                var lines=div.innerText.split('\n');var rows=[];
                for(var i=0;i<lines.length;i++){
                    if(lines[i].trim()){var cells=lines[i].split('\t');rows.push(cells.map(function(c){return c.trim();}));}
                }
                if(rows.length>0)return JSON.stringify(rows);
            }
            return JSON.stringify({raw:document.body.innerText.substring(0,5000)});
        })()"""
        result = driver.execute_script(js)
        if not result: return []
        data = json.loads(result)
        if isinstance(data, dict) and "raw" in data:
            logger.warning("\u672a\u627e\u5230\u8868\u683c\u5143\u7d20\uff0c\u89e3\u6790\u539f\u59cb\u6587\u672c")
            lines = data["raw"].split("\n")
            rows = []
            for line in lines:
                if line.strip():
                    cells = line.split("\t")
                    if len(cells) > 1: rows.append([c.strip() for c in cells])
            return rows
        return data

    def run(self):
        try:
            self.gui.set_status("\u6279\u91cf\u53d1\u5e03\u4e2d...")
            cfg = load_config(); api = self.gui.get_api()
            mem = load_memory()
            published = set(mem.get("posted_dramas", []))

            driver = self.gui.shared_driver
            if driver is None or driver.driver is None:
                driver = WeiboDriver(cfg.get("weibo_url","https://weibo.com"))
                driver.start(); self.gui.shared_driver = driver

            # Load data
            if self.is_wps:
                rows_raw = self._read_wps_table(driver)
                if not rows_raw:
                    logger.error("WPS\u8868\u683c\u8bfb\u53d6\u5931\u8d25")
                    self.gui.set_status("WPS\u8bfb\u53d6\u5931\u8d25"); return
                headers = rows_raw[0] if rows_raw else []
                logger.info(f"\u8868\u5934: {headers}")
                self.tasks = []
                for row in rows_raw[1:]:
                    d = {}
                    for i, h in enumerate(headers):
                        if i < len(row): d[h] = row[i]
                    if d.get("\u5267\u540d"): self.tasks.append(d)
                logger.info(f"\u5171\u8bfb\u53d6{len(self.tasks)}\u6761\u6570\u636e")
                # Switch to weibo tab
                driver.driver.get(cfg.get("weibo_url","https://weibo.com"))
                time.sleep(5)
            else:
                with open(self.source,"r",encoding="utf-8-sig") as f:
                    self.tasks = list(csv.DictReader(f))
                logger.info(f"\u5171{len(self.tasks)}\u6761\u6570\u636e")

            # Fill first task to GUI
            if self.tasks:
                first = self.tasks[0] if self.start_row<=2 else (self.tasks[self.start_row-2] if self.start_row-2<len(self.tasks) else self.tasks[0])
                self._fill_gui(first)
                time.sleep(1)

            count = 0
            for idx, row in enumerate(self.tasks):
                if self.gui.stop_flag: break
                if idx+2 < self.start_row: continue
                drama = row.get("\u5267\u540d","").strip()
                orig = row.get("\u539f\u540d","").strip()
                key = f"{drama}|{orig}"
                if not drama: continue
                if key in published:
                    logger.info(f"\u8df3\u8fc7\u5df2\u53d1\u5e03: {drama}"); continue
                poster = row.get("\u6d77\u62a5URL","").strip()
                if not poster: logger.warning(f"{drama} \u65e0\u6d77\u62a5URL"); continue

                self._fill_gui(row)
                time.sleep(1)

                count += 1
                self.gui.set_status(f"\u6279\u91cf {count}: {drama}")
                logger.info(f"--- \u6279\u91cf\u7b2c{count}\u6761: {drama} ---")

                try:
                    fields = {"drama":drama,"original":orig,"year":row.get("\u5e74\u4efd","").strip(),
                              "alias":row.get("\u53c8\u540d","").strip(),"season":row.get("\u5b63\u6570","").strip(),
                              "type":row.get("\u7c7b\u578b","").strip(),"episodes":row.get("\u96c6\u6570","").strip(),
                              "poster":poster,"pan":row.get("\u5938\u514b\u94fe\u63a5","").strip(),
                              "baidu":row.get("\u767e\u5ea6\u94fe\u63a5","").strip(),
                              "tag":row.get("\u6807\u7b7e","").strip() or "\u7535\u89c6\u5267","comment_lines":[]}
                    if fields["pan"]: fields["comment_lines"].append(f"\u5938\uff1a{fields['pan']}")
                    if fields["baidu"]: fields["comment_lines"].append(f"\u5ea6\uff1a{fields['baidu']}")

                    review = generate_review(drama, orig, fields["year"], api)
                    text = format_text(drama, orig, fields["year"], fields["alias"],
                                      fields["season"], fields["type"], fields["episodes"],
                                      review, fields["tag"])
                    img = download_poster(poster, drama)
                    ok = driver.publish(text, img, cfg.get("max_retries",3))
                    if ok:
                        time.sleep(5); uid = cfg.get("weibo_userid","")
                        for line in fields["comment_lines"]: driver.comment(line, uid)
                        logger.info(f"\u5df2\u53d1\u5e03: {drama}")
                        published.add(key); mem.setdefault("posted_dramas",[]).append(key); save_memory(mem)
                    else: logger.error(f"\u53d1\u5e03\u5931\u8d25: {drama}")
                    cleanup_temp(drama)
                except Exception as e: logger.error(f"{drama} \u5f02\u5e38: {e}")

                if not self.gui.stop_flag:
                    logger.info(f"\u7b49\u5f85{self.interval//60}\u5206\u949f...")
                    for _ in range(self.interval):
                        if self.gui.stop_flag: break; time.sleep(1)

            logger.info(f"\u6279\u91cf\u5b8c\u6210\uff0c\u5171{count}\u6761")
            self.gui.set_status(f"\u6279\u91cf\u5b8c\u6210\uff0c\u5171{count}\u6761")
        except Exception as e:
            logger.error(f"\u6279\u91cf\u5f02\u5e38: {e}")
            self.gui.set_status("\u53d1\u53d1\u5f02\u5e38\uff0c\u8bf7\u67e5\u770b\u65e5\u5fd7")
        finally:
            self.gui.set_buttons(True)
            self.gui.btn_batch.setEnabled(True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YLFile 微博发布工具")
        self.setGeometry(80, 80, 1050, 750)
        self.is_paused = False
        self.stop_flag = False
        self.memory = load_memory()
        self.config = load_config()
        self.shared_driver = None
        self.live_worker = None

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
            QPushButton#save {{ background: #27ae60; color: white; }}
            QPushButton#save:hover {{ background: #219a52; }}
            QPushButton#live {{ background: #e67e22; color: white; }}
            QPushButton#live:hover {{ background: #d35400; }}
            QPushButton#tpl {{ background: #8e44ad; color: white; }}
            QPushButton#tpl:hover {{ background: #7d3c98; }}
            QPushButton#pause {{ background: #f39c12; color: white; }}
            QPushButton#pause:hover {{ background: #e67e22; }}
            QPushButton#stop {{ background: #e74c3c; color: white; }}
            QPushButton#stop:hover {{ background: #c0392b; }}
            QPushButton:disabled {{ background: #bbb; color: #888; }}
            QSpinBox {{ padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-family: {FONT}; font-size: {FS}px; min-height: 24px; }}
            QLabel {{ font-family: {FONT}; font-size: {FS}px; color: #333; }}
            QGroupBox QLabel {{ font-weight: normal; }}
            QMessageBox {{ font-family: Microsoft YaHei; font-size: 13px; }}
            QMessageBox QLabel {{ font-family: Microsoft YaHei; font-size: 13px; min-width: 300px; }}
            QMessageBox QPushButton {{ font-family: Microsoft YaHei; font-size: 12px; padding: 6px 20px; min-width: 80px; }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(10, 8, 10, 8)
        ml.setSpacing(6)

        # ===== Top row: 发布内容 + API设置 (equal width) =====
        top = QHBoxLayout()
        top.setSpacing(10)

        # Left: 发布内容
        lb = QGroupBox("发布内容")
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
        top.addWidget(lb, stretch=1)

        # Right side: API设置 + 日志 stacked vertically
        right_stack = QVBoxLayout()
        right_stack.setSpacing(6)

        # API设置
        rb = QGroupBox("API设置")
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

        self.btn_save = QPushButton("保存设置")
        self.btn_save.setObjectName("save")
        self.btn_save.clicked.connect(self._save_cfg)
        rf.addRow("", self.btn_save)

        rb.setLayout(rf)
        right_stack.addWidget(rb)

        # 运行日志 (under API settings)
        lg = QGroupBox("运行日志")
        lgl = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
            "background:#1a1a2e;color:#e0e0e0;font-family:Consolas,Microsoft YaHei;font-size:10pt;"
            "border:1px solid #333;border-radius:4px;padding:4px;")
        lgl.addWidget(self.log_area)
        lg.setLayout(lgl)
        right_stack.addWidget(lg, stretch=1)

        top.addLayout(right_stack, stretch=1)
        ml.addLayout(top, stretch=3)

        # ===== Buttons row =====
        bl = QHBoxLayout()
        self.btn_pub = QPushButton("一键发布")
        self.btn_pub.setObjectName("pub")
        self.btn_pub.clicked.connect(self.on_pub)
        bl.addWidget(self.btn_pub)

        self.btn_pause = QPushButton("暂停")
        self.btn_pause.setObjectName("pause")
        self.btn_pause.clicked.connect(self.on_pause)
        self.btn_pause.setEnabled(False)
        bl.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setEnabled(False)
        bl.addWidget(self.btn_stop)

        self.btn_batch = QPushButton("批量发布")
        self.btn_batch.setObjectName("live")
        self.btn_batch.clicked.connect(self.on_batch)
        self.btn_batch.setEnabled(False)
        bl.addWidget(self.btn_batch)

        bl.addSpacing(20)
        bl.addWidget(QLabel("发布间隔(分钟):"))
        self.spn_int = QSpinBox()
        self.spn_int.setRange(1, 60)
        self.spn_int.setValue(self.config.get("default_interval", 5))
        self.spn_int.setMaximumWidth(55)
        bl.addWidget(self.spn_int)

        bl.addWidget(QLabel("用户ID:"))
        self.inp_uid = QLineEdit(self.config.get("weibo_userid", ""))
        self.inp_uid.setPlaceholderText("评论用")
        bl.addWidget(self.inp_uid)

        bl.addStretch()
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

        # ===== 实时表格 =====
        tg = QGroupBox("实时表格关联")
        tll = QHBoxLayout()
        tll.addWidget(QLabel("表格:"))
        self.inp_csv = QLineEdit()
        self.inp_csv.setPlaceholderText("本地CSV路径 或 WPS分享链接")
        self.inp_csv.textChanged.connect(self._on_csv_changed)
        tll.addWidget(self.inp_csv, stretch=1)
        self.btn_browse = QPushButton("本地选择")
        self.btn_browse.setObjectName("tpl")
        self.btn_browse.clicked.connect(self._browse)
        tll.addWidget(self.btn_browse)
        self.btn_tpl = QPushButton("下载模板")
        self.btn_tpl.setObjectName("tpl")
        self.btn_tpl.clicked.connect(self._download_template)
        tll.addWidget(self.btn_tpl)
        tll.addWidget(QLabel("起始行:"))
        self.spn_start_row = QSpinBox()
        self.spn_start_row.setRange(1, 10000)
        self.spn_start_row.setValue(2)
        self.spn_start_row.setMaximumWidth(60)
        tll.addWidget(self.spn_start_row)
        self.btn_live = QPushButton("开启实时监听")
        self.btn_live.setObjectName("live")
        self.btn_live.clicked.connect(self._toggle_live)
        tll.addWidget(self.btn_live)
        tg.setLayout(tll)
        ml.addWidget(tg)

        # Status
        self.lbl_st = QLabel("就绪")
        self.lbl_st.setStyleSheet("font-family:Microsoft YaHei;font-size:13px;color:#666;padding:4px;")
        ml.addWidget(self.lbl_st)

        self._restore()
        log_sig.msg.connect(self._add_log)

    def _add_log(self, m):
        self.log_area.append(m)
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_status(self, t):
        self.lbl_st.setText(t)

    def set_buttons(self, ok):
        self.btn_pub.setEnabled(ok)
        self.btn_pause.setEnabled(not ok)
        self.btn_stop.setEnabled(not ok)
        if not ok: self.btn_batch.setEnabled(False)

    def _save_cfg(self):
        self.config["api_base"] = self.inp_api_base.text().strip()
        self.config["api_key"] = self.inp_api_key.text().strip()
        self.config["model"] = self.inp_api_model.text().strip()
        self.config["weibo_userid"] = self.inp_uid.text().strip()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        logger.info("设置已保存")

    def get_api(self):
        return {"api_base": self.inp_api_base.text().strip(),
                "api_key": self.inp_api_key.text().strip(),
                "model": self.inp_api_model.text().strip()}

    def _restore(self):
        lf = self.memory.get("last_fields", {})
        for k, w in [("drama", self.inp_drama), ("original", self.inp_original),
                     ("year", self.inp_year), ("alias", self.inp_alias),
                     ("type", self.inp_type), ("season", self.inp_season),
                     ("episodes", self.inp_episodes), ("poster", self.inp_poster),
                     ("pan", self.inp_pan), ("baidu", self.inp_baidu),
                     ("tag", self.inp_tag)]:
            if lf.get(k): w.setText(lf[k])
        if lf: logger.info(f"恢复上次输入: {lf.get('drama', '')}")

    def _fields(self):
        return {"drama": self.inp_drama.text().strip(), "original": self.inp_original.text().strip(),
                "year": self.inp_year.text().strip(), "alias": self.inp_alias.text().strip(),
                "type": self.inp_type.text().strip(), "season": self.inp_season.text().strip(),
                "episodes": self.inp_episodes.text().strip(), "poster": self.inp_poster.text().strip(),
                "pan": self.inp_pan.text().strip(), "baidu": self.inp_baidu.text().strip(),
                "tag": self.inp_tag.text().strip() or "电视剧"}

    def _is_dup(self, d, o):
        return f"{d}|{o}" in self.memory.get("posted_dramas", [])

    def on_pause(self):
        self.is_paused = not self.is_paused
        self.btn_pause.setText("继续" if self.is_paused else "暂停")

    def on_stop(self):
        self.stop_flag = True
        self.is_paused = False
        self.set_buttons(True)
        self.btn_batch.setEnabled(hasattr(self, 'tasks') and len(self.tasks) > 0)
        self.set_status("已停止")
        logger.info("用户点击停止")
    def on_batch(self):
        source = self.inp_csv.text().strip()
        logger.info(f"批量发布: {source}")
        if not source:
            QMessageBox.warning(self, "提示", "请先填入CSV路径或WPS链接"); return
        self.stop_flag = False
        self.set_buttons(False)
        self.btn_batch.setEnabled(True)
        is_wps = "wps.cn" in source or "kdocs.cn" in source
        logger.info(f"启动批量发布 (WPS={is_wps})...")
        BatchPublishWorker(self, source, self.spn_int.value() * 60,
                          self.spn_start_row.value(), is_wps=is_wps).start()

    def on_pub(self):
        f = self._fields()
        if not f["drama"]:
            QMessageBox.warning(self, "提示", "请填写剧名"); return
        if not f["poster"]:
            QMessageBox.warning(self, "提示", "请填写海报URL"); return
        if self._is_dup(f["drama"], f["original"]):
            if QMessageBox.question(self, "重复", f"{f['drama']}已发布。再次发布？",
                                   QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        f["comment_lines"] = []
        if f["pan"]: f["comment_lines"].append(f"夸：{f['pan']}")
        if f["baidu"]: f["comment_lines"].append(f"度：{f['baidu']}")
        self.stop_flag = False
        self.set_buttons(False)
        PublishWorker(self, f).start()

    def _on_csv_changed(self):
        if self.inp_csv.text().strip():
            self.btn_batch.setEnabled(True)
    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "CSV", "", "CSV (*.csv)")
        if p: self.inp_csv.setText(p)

    def _download_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "weibo_template.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["剧名","原名","年份","又名","类型","季数","集数","海报URL","夸克链接","百度链接","标签"])
            w.writerow(["狂飙","The Knockout","2023","狂飙","剧情","","39","https://img.doubanio.com/xxx.jpg","https://pan.quark.cn/s/abc","","电视剧"])
        logger.info(f"模板已保存: {path}")
        QMessageBox.information(self, "成功", "模板已保存到: " + path)

    def _resolve_csv_path(self):
        source = self.inp_csv.text().strip()
        if not source: return None
        if os.path.exists(source): return source
        return None

    def _toggle_live(self):
        if self.live_worker and self.live_worker.is_alive():
            self.stop_flag = True
            self.live_worker = None
            self.btn_live.setText("开启实时监听")
            return
        csv_path = self.inp_csv.text().strip()
        if not csv_path:
            QMessageBox.warning(self, "提示", "请选择CSV"); return
        self.stop_flag = False
        self.set_buttons(False)
        self.live_worker = LiveTableWorker(self, csv_path, self.spn_int.value() * 60)
        self.live_worker.start_row = self.spn_start_row.value()
        self.live_worker.start()
        self.btn_live.setText("停止监听")
        self.set_status("实时监听中...")

    def _add_log(self,m): self.log_area.append(m); sb=self.log_area.verticalScrollBar(); sb.setValue(sb.maximum())
    def set_status(self,t): self.lbl_st.setText(t)
    def set_buttons(self,ok): self.btn_pub.setEnabled(ok); self.btn_pause.setEnabled(not ok); self.btn_stop.setEnabled(not ok)
    def _save_cfg(self):
        self.config["api_base"]=self.inp_api_base.text().strip(); self.config["api_key"]=self.inp_api_key.text().strip()
        self.config["model"]=self.inp_api_model.text().strip(); self.config["weibo_userid"]=self.inp_uid.text().strip()
        with open(CONFIG_FILE,"w",encoding="utf-8") as f: json.dump(self.config,f,ensure_ascii=False,indent=2)
        logger.info("设置已保存")
    def get_api(self): return{"api_base":self.inp_api_base.text().strip(),"api_key":self.inp_api_key.text().strip(),"model":self.inp_api_model.text().strip()}
    def _restore(self):
        lf=self.memory.get("last_fields",{})
        for k,w in[("drama",self.inp_drama),("original",self.inp_original),("year",self.inp_year),
                    ("alias",self.inp_alias),("type",self.inp_type),("season",self.inp_season),
                    ("episodes",self.inp_episodes),("poster",self.inp_poster),
                    ("pan",self.inp_pan),("baidu",self.inp_baidu),("tag",self.inp_tag)]:
            if lf.get(k): w.setText(lf[k])
        if lf: logger.info(f"恢复上次输入: {lf.get('drama','')}")
    def _fields(self):
        return{"drama":self.inp_drama.text().strip(),"original":self.inp_original.text().strip(),
               "year":self.inp_year.text().strip(),"alias":self.inp_alias.text().strip(),
               "type":self.inp_type.text().strip(),"season":self.inp_season.text().strip(),
               "episodes":self.inp_episodes.text().strip(),"poster":self.inp_poster.text().strip(),
               "pan":self.inp_pan.text().strip(),"baidu":self.inp_baidu.text().strip(),
               "tag":self.inp_tag.text().strip() or "电视剧"}
    def _is_dup(self,d,o): return f"{d}|{o}" in self.memory.get("posted_dramas",[])
    def on_pause(self): self.is_paused=not self.is_paused; self.btn_pause.setText("继续" if self.is_paused else "暂停")
    def on_stop(self): self.stop_flag=True; self.is_paused=False; self.set_buttons(True); self.set_status("已停止")
    def on_pub(self):
        f=self._fields()
        if not f["drama"]: QMessageBox.warning(self,"提示","请填写剧名"); return
        if not f["poster"]: QMessageBox.warning(self,"提示","请填写海报URL"); return
        if self._is_dup(f["drama"],f["original"]):
            if QMessageBox.question(self,"重复",f"{f['drama']}已发布。再次发布？",
                                   QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes: return
        f["comment_lines"]=[]
        if f["pan"]: f["comment_lines"].append(f"夸：{f['pan']}")
        if f["baidu"]: f["comment_lines"].append(f"度：{f['baidu']}")
        self.stop_flag=False; self.set_buttons(False); PublishWorker(self,f).start()
    def _browse(self):
        p,_=QFileDialog.getOpenFileName(self,"CSV","","CSV (*.csv)")
        if p: self.inp_csv.setText(p)
    def _download_template(self):
        path,_=QFileDialog.getSaveFileName(self,"保存模板","weibo_template.csv","CSV (*.csv)")
        if not path: return
        with open(path,"w",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f)
            w.writerow(["剧名","原名","年份","又名","类型","季数","集数","海报URL","夸克链接","百度链接","标签"])
            w.writerow(["狂飙","The Knockout","2023","狂飙","剧情","","39","https://img.doubanio.com/xxx.jpg","https://pan.quark.cn/s/abc","","电视剧"])
        logger.info(f"模板已保存: {path}")
        QMessageBox.information(self,"成功",f"模板已保存到:\n{path}")
    def _resolve_csv_path(self):
        source=self.inp_csv.text().strip()
        if not source: return None
        if "wps.cn" in source or "kdocs.cn" in source:
            logger.info("检测到WPS链接")
            try:
                download_url=source
                if "/share/" in source: download_url=source.replace("/share/","/share/export/download/")
                elif "?" in source: download_url=source+"&export=1"
                else: download_url=source+"/export/download/"
                resp=req_lib.get(download_url,timeout=30,verify=False,allow_redirects=True)
                if resp.status_code==200:
                    import tempfile; tmp=os.path.join(tempfile.gettempdir(),"wps_data.csv")
                    with open(tmp,"wb") as f: f.write(resp.content)
                    return tmp
                else: logger.error(f"WPS下载失败: HTTP {resp.status_code}"); return None
            except Exception as e: logger.error(f"WPS获取失败: {e}"); return None
        if os.path.exists(source): return source
        logger.error(f"文件不存在: {source}"); return None
    def _toggle_live(self):
        if self.live_worker and self.live_worker.is_alive():
            self.stop_flag=True; self.live_worker=None; self.btn_live.setText("▶ 开启实时监听"); return
        csv_path=self.inp_csv.text().strip()
        if not csv_path: QMessageBox.warning(self,"提示","请选择CSV"); return
        self.stop_flag=False; self.set_buttons(False)
        self.live_worker=LiveTableWorker(self,csv_path,self.spn_int.value()*60)
        self.live_worker.start_row=self.spn_start_row.value()
        self.live_worker.start()
        self.btn_live.setText("⏹ 停止监听"); self.set_status("实时监听中...")


def main():
    setup_logging(); logger.info("YLFile v4.0 启动")
    app=QApplication(sys.argv); w=MainWindow(); w.show(); sys.exit(app.exec_())

if __name__=="__main__": main()
