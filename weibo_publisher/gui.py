"""
GUI界面模块
使用Tkinter构建YLFile微博发布工具的图形界面
包含：输入表单、一键发布、暂停/继续、CSV导入、日志显示、记忆功能
"""

import os
import csv
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from pathlib import Path


class WeiboPublisherGUI:
    """YLFile微博发布工具的主界面"""

    # 记忆文件路径
    MEMORY_FILE = Path(__file__).parent / "memory.json"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("YLFile微博发布工具")
        self.root.geometry("720x900")
        self.root.resizable(True, True)

        # 状态变量
        self.is_paused = False
        self.is_running = False
        self.stop_flag = False
        self.tasks = []
        self.current_task_index = 0
        self._current_publisher = None  # 当前的publisher实例

        # 加载配置
        self.config = self._load_config()

        # ★ 加载上次记忆
        self.memory = self._load_memory()

        # 构建界面
        self._build_ui()

        # ★ 恢复上次输入的内容
        self._restore_memory()

    # ================================================================
    # 配置与记忆
    # ================================================================

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent / "config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "api_base": "https://api.deepseek.com/v1",
                "api_key": "sk-xxx",
                "model": "deepseek-chat",
                "default_interval": 5,
                "max_retries": 3,
                "temp_folder": "./temp",
                "weibo_url": "https://weibo.com",
                "headless": False,
            }

    def _load_memory(self) -> dict:
        """加载记忆文件，记录上次发布的剧名等信息"""
        try:
            if self.MEMORY_FILE.exists():
                with open(self.MEMORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"last_drama": "", "last_episode": "", "last_pan": "", "posted_dramas": []}

    def _save_memory(self):
        """保存当前输入到记忆文件"""
        self.memory["last_drama"] = self.drama_name_var.get().strip()
        self.memory["last_episode"] = self.episode_info_var.get().strip()
        self.memory["last_pan"] = self.pan_link_var.get().strip()
        try:
            with open(self.MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存记忆失败: {e}")

    def _restore_memory(self):
        """恢复上次输入的内容到界面"""
        if self.memory.get("last_drama"):
            self.drama_name_var.set(self.memory["last_drama"])
            self.log(f"已恢复上次输入：《{self.memory['last_drama']}》", "INFO")
        if self.memory.get("last_episode"):
            self.episode_info_var.set(self.memory["last_episode"])
        if self.memory.get("last_pan"):
            self.pan_link_var.set(self.memory["last_pan"])

    def _mark_posted(self, drama_name: str):
        """标记某部剧已发布（防重复）"""
        if drama_name not in self.memory.get("posted_dramas", []):
            self.memory.setdefault("posted_dramas", []).append(drama_name)
            self._save_memory()

    def _check_duplicate(self, drama_name: str) -> bool:
        """检查是否已发布过该剧，返回True表示是重复"""
        return drama_name in self.memory.get("posted_dramas", [])

    # ================================================================
    # 构建界面
    # ================================================================

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(
            main_frame, text="🎬 YLFile微博发布工具",
            font=("微软雅黑", 16, "bold")
        )
        title_label.pack(pady=(0, 10))

        # ============================================================
        # 输入表单
        # ============================================================
        form_frame = ttk.LabelFrame(main_frame, text="📝 发布信息", padding=10)
        form_frame.pack(fill=tk.X, pady=(0, 5))

        # 剧名
        ttk.Label(form_frame, text="剧名：").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.drama_name_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.drama_name_var, width=50).grid(
            row=0, column=1, sticky=tk.EW, padx=(5, 0), pady=3
        )

        # 集数信息
        ttk.Label(form_frame, text="集数/季数：").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.episode_info_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.episode_info_var, width=50).grid(
            row=1, column=1, sticky=tk.EW, padx=(5, 0), pady=3
        )

        # 海报URL
        ttk.Label(form_frame, text="海报URL：").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.poster_url_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.poster_url_var, width=50).grid(
            row=2, column=1, sticky=tk.EW, padx=(5, 0), pady=3
        )

        # ★ 夸克网盘链接
        ttk.Label(form_frame, text="夸克链接：").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.pan_link_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.pan_link_var, width=50).grid(
            row=3, column=1, sticky=tk.EW, padx=(5, 0), pady=3
        )

        # ★ 百度网盘链接
        ttk.Label(form_frame, text="百度链接：").grid(row=4, column=0, sticky=tk.W, pady=3)
        self.baidu_link_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.baidu_link_var, width=50).grid(
            row=4, column=1, sticky=tk.EW, padx=(5, 0), pady=3
        )

        # 发布间隔
        ttk.Label(form_frame, text="发布间隔(分钟)：").grid(row=5, column=0, sticky=tk.W, pady=3)
        self.interval_var = tk.IntVar(value=self.config.get("default_interval", 5))
        ttk.Spinbox(
            form_frame, from_=1, to=60, textvariable=self.interval_var, width=10
        ).grid(row=5, column=1, sticky=tk.W, padx=(5, 0), pady=3)

        form_frame.columnconfigure(1, weight=1)

        # ============================================================
        # 操作按钮
        # ============================================================
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.publish_btn = ttk.Button(
            btn_frame, text="🚀 一键发布", command=self._on_single_publish
        )
        self.publish_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.pause_btn = ttk.Button(
            btn_frame, text="⏸ 暂停", command=self._on_pause_toggle, state=tk.DISABLED
        )
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_btn = ttk.Button(
            btn_frame, text="⏹ 停止", command=self._on_stop, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        self.import_csv_btn = ttk.Button(
            btn_frame, text="📂 导入CSV", command=self._on_import_csv
        )
        self.import_csv_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.batch_publish_btn = ttk.Button(
            btn_frame, text="🔄 批量发布", command=self._on_batch_publish, state=tk.DISABLED
        )
        self.batch_publish_btn.pack(side=tk.LEFT)

        # ============================================================
        # 任务列表
        # ============================================================
        self.task_frame = ttk.LabelFrame(main_frame, text="📋 任务列表 (CSV)", padding=5)
        self.task_frame.pack(fill=tk.X, pady=(0, 5))

        columns = ("index", "drama", "episode", "poster", "pan")
        self.task_tree = ttk.Treeview(
            self.task_frame, columns=columns, show="headings", height=4
        )
        self.task_tree.heading("index", text="#")
        self.task_tree.heading("drama", text="剧名")
        self.task_tree.heading("episode", text="集数信息")
        self.task_tree.heading("poster", text="海报URL")
        self.task_tree.heading("pan", text="网盘链接")
        self.task_tree.column("index", width=30)
        self.task_tree.column("drama", width=120)
        self.task_tree.column("episode", width=100)
        self.task_tree.column("poster", width=200)
        self.task_tree.column("pan", width=200)

        scrollbar = ttk.Scrollbar(
            self.task_frame, orient=tk.VERTICAL, command=self.task_tree.yview
        )
        self.task_tree.configure(yscrollcommand=scrollbar.set)
        self.task_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ============================================================
        # 日志区域
        # ============================================================
        log_frame = ttk.LabelFrame(main_frame, text="📜 运行日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=15, wrap=tk.WORD,
            font=("Consolas", 9), state=tk.DISABLED,
            bg="#1e1e1e", fg="#d4d4d4",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=3
        ).pack(fill=tk.X, pady=(5, 0))

    # ================================================================
    # 日志
    # ================================================================

    def log(self, message: str, level: str = "INFO"):
        timestamp = time.strftime("%H:%M:%S")
        prefix_map = {"INFO": "ℹ️ ", "WARNING": "⚠️ ", "ERROR": "❌ ", "SUCCESS": "✅ "}
        line = f"[{timestamp}] {prefix_map.get(level, '  ')}{message}\n"
        self.root.after(0, self._append_log, line)

    def _append_log(self, line: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ================================================================
    # 登录确认弹窗
    # ================================================================

    def _show_login_dialog(self):
        self.root.after(0, self._create_login_dialog)

    def _create_login_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("微博登录确认")
        dlg.geometry("380x140")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.update_idletasks()
        x = (dlg.winfo_screenwidth() - 380) // 2
        y = (dlg.winfo_screenheight() - 140) // 2
        dlg.geometry(f"+{x}+{y}")

        ttk.Label(
            dlg,
            text="👉 请在浏览器中完成微博登录\n登录成功后点击下方按钮确认",
            font=("微软雅黑", 11), justify=tk.CENTER,
        ).pack(pady=(15, 10))

        def on_confirm():
            if self._current_publisher:
                self._current_publisher._login_confirmed_by_user = True
            dlg.destroy()

        ttk.Button(dlg, text="✅ 我已登录", command=on_confirm).pack(pady=5)
        dlg.protocol("WM_DELETE_WINDOW", on_confirm)

    # ================================================================
    # 按钮事件
    # ================================================================

    def _on_single_publish(self):
        drama = self.drama_name_var.get().strip()
        episode = self.episode_info_var.get().strip()
        poster = self.poster_url_var.get().strip()
        pan = self.pan_link_var.get().strip()

        if not drama:
            messagebox.showwarning("提示", "请输入剧名")
            return
        if not poster:
            messagebox.showwarning("提示", "请输入海报URL")
            return
        if not pan:
            messagebox.showwarning("提示", "请输入夸克网盘链接")
            return

        # ★ 检查是否重复发布
        if self._check_duplicate(drama):
            result = messagebox.askyesno(
                "重复发布提醒",
                f"《{drama}》之前已经发布过了！\n\n确定要再次发布吗？"
            )
            if not result:
                return

        self._set_buttons_running(True)
        self.is_paused = False
        self.stop_flag = False

        thread = threading.Thread(
            target=self._publish_single_task,
            args=(drama, episode, poster, pan),
            daemon=True,
        )
        thread.start()

    def _on_pause_toggle(self):
        if self.is_paused:
            self.is_paused = False
            self.pause_btn.config(text="⏸ 暂停")
            self.log("▶️ 已继续发布", "INFO")
        else:
            self.is_paused = True
            self.pause_btn.config(text="▶️ 继续")
            self.log("⏸ 已暂停发布", "INFO")

    def _on_stop(self):
        self.stop_flag = True
        self.is_paused = False
        self.log("⏹ 正在停止...", "INFO")

    def _on_import_csv(self):
        filepath = filedialog.askopenfilename(
            title="选择CSV文件",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not filepath:
            return
        try:
            self.tasks = []
            for item in self.task_tree.get_children():
                self.task_tree.delete(item)

            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                required_cols = {"剧名", "集数信息", "海报URL", "网盘链接"}
                if not required_cols.issubset(set(reader.fieldnames or [])):
                    messagebox.showerror(
                        "格式错误",
                        f"CSV列名必须包含：{', '.join(required_cols)}\n"
                        f"实际列名：{', '.join(reader.fieldnames or [])}"
                    )
                    return
                for i, row in enumerate(reader, 1):
                    task = {
                        "drama": row["剧名"].strip(),
                        "episode": row["集数信息"].strip(),
                        "poster": row["海报URL"].strip(),
                        "pan": row["网盘链接"].strip(),
                    }
                    self.tasks.append(task)
                    short_poster = task["poster"][:40] + "..." if len(task["poster"]) > 40 else task["poster"]
                    short_pan = task["pan"][:40] + "..." if len(task["pan"]) > 40 else task["pan"]
                    self.task_tree.insert("", tk.END, values=(
                        i, task["drama"], task["episode"], short_poster, short_pan
                    ))
            self.log(f"成功导入 {len(self.tasks)} 条任务", "SUCCESS")
            self.batch_publish_btn.config(state=tk.NORMAL)
            self.status_var.set(f"已加载 {len(self.tasks)} 条任务")
        except Exception as e:
            messagebox.showerror("导入失败", f"读取CSV文件失败：\n{e}")
            self.log(f"CSV导入失败: {e}", "ERROR")

    def _on_batch_publish(self):
        if not self.tasks:
            messagebox.showwarning("提示", "没有可发布的任务，请先导入CSV")
            return
        self.current_task_index = 0
        self._set_buttons_running(True)
        self.is_paused = False
        self.stop_flag = False
        thread = threading.Thread(target=self._batch_publish_loop, daemon=True)
        thread.start()

    def _set_buttons_running(self, running: bool):
        state = tk.DISABLED if running else tk.NORMAL
        self.root.after(0, self._update_buttons, state)

    def _update_buttons(self, state):
        self.publish_btn.config(state=state)
        self.import_csv_btn.config(state=state)
        self.batch_publish_btn.config(state=state)
        if state == tk.DISABLED:
            self.pause_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.pause_btn.config(state=state, text="⏸ 暂停")
            self.stop_btn.config(state=state)
            self.is_running = False

    # ================================================================
    # ★ 构建评论文案（支持 夸： 和 度： 两种网盘链接）
    # ================================================================

    def _build_comment_lines(self, pan: str, baidu: str = "") -> list:
        """
        构建评论区内容列表

        Returns:
            评论文本列表，如 ["夸：https://...", "度：https://..."]
        """
        lines = []
        if pan and pan.strip():
            lines.append(f"夸：{pan.strip()}")
        if baidu and baidu.strip():
            lines.append(f"度：{baidu.strip()}")
        return lines

    # ================================================================
    # 单条发布任务
    # ================================================================

    def _publish_single_task(self, drama: str, episode: str, poster: str, pan: str):
        try:
            self.is_running = True

            from publisher import WeiboPublisher
            from ai_client import generate_review
            from downloader import download_poster, cleanup_temp

            self.log("🚀 开始发布...", "INFO")

            # 启动浏览器
            self.log("正在启动浏览器...", "INFO")
            headless = self.config.get("headless", False)
            publisher = WeiboPublisher(
                weibo_url=self.config.get("weibo_url", "https://weibo.com"),
                headless=headless,
            )
            self._current_publisher = publisher
            publisher._on_login_prompt = self._show_login_dialog
            publisher.start_browser()

            try:
                # AI生成影评
                self.log(f"正在为《{drama}》生成AI影评...", "INFO")
                ai_review = generate_review(drama)
                self.log(f"AI影评（{len(ai_review)}字）：{ai_review}", "SUCCESS")

                # 拼接文案
                full_text = publisher.compose_text(drama, episode, ai_review)
                self.log(f"完整文案：{full_text}", "INFO")

                # 下载海报
                self.log("正在下载海报图片...", "INFO")
                image_path = download_poster(poster, drama)
                self.log(f"海报已下载: {image_path}", "SUCCESS")

                # 发布微博
                self.log("正在发布微博...", "INFO")
                max_retries = self.config.get("max_retries", 3)
                success = publisher.publish(full_text, image_path, max_retries)

                if success:
                    # ★ 发布成功后，构建评论内容（夸+度）
                    baidu = self.baidu_link_var.get().strip()
                    comment_lines = self._build_comment_lines(pan, baidu)

                    for line in comment_lines:
                        self.log(f"正在发送评论: {line}", "INFO")
                        publisher.comment_on_post(line, max_retries)

                    self.log(f"🎉 《{drama}》发布完成！", "SUCCESS")
                    self.status_var.set(f"✅ 《{drama}》发布成功")

                    # ★ 记忆：标记已发布
                    self._mark_posted(drama)
                    self._save_memory()
                else:
                    self.log(f"《{drama}》发布失败", "ERROR")
                    self.status_var.set(f"❌ 《{drama}》发布失败")

            finally:
                cleanup_temp(drama)
                publisher.close()

        except Exception as e:
            self.log(f"发布异常: {e}", "ERROR")
            self.status_var.set(f"❌ 异常: {e}")
        finally:
            self.is_running = False
            self._set_buttons_running(False)

    # ================================================================
    # 批量发布
    # ================================================================

    def _batch_publish_loop(self):
        from publisher import WeiboPublisher
        from ai_client import generate_review
        from downloader import download_poster, cleanup_temp

        self.log(f"🔄 开始批量发布，共 {len(self.tasks)} 条，间隔 {self.interval_var.get()} 分钟", "INFO")

        headless = self.config.get("headless", False)
        publisher = WeiboPublisher(
            weibo_url=self.config.get("weibo_url", "https://weibo.com"),
            headless=headless,
        )
        self._current_publisher = publisher
        publisher._on_login_prompt = self._show_login_dialog

        try:
            publisher.start_browser()
        except Exception as e:
            self.log(f"浏览器启动失败: {e}", "ERROR")
            self._set_buttons_running(False)
            return

        try:
            for i, task in enumerate(self.tasks):
                if self.stop_flag:
                    self.log("⏹ 批量发布已停止", "WARNING")
                    break
                while self.is_paused:
                    if self.stop_flag:
                        break
                    time.sleep(1)
                if self.stop_flag:
                    break

                drama = task["drama"]
                episode = task["episode"]
                poster = task["poster"]
                pan = task["pan"]

                self.current_task_index = i + 1
                self.log(f"--- 第 {i+1}/{len(self.tasks)} 条: 《{drama}》 ---", "INFO")
                self.status_var.set(f"发布中: {i+1}/{len(self.tasks)} - 《{drama}》")

                try:
                    # 检查重复
                    if self._check_duplicate(drama):
                        self.log(f"⚠️ 《{drama}》之前已发布过，跳过", "WARNING")
                        continue

                    self.log(f"正在为《{drama}》生成AI影评...", "INFO")
                    ai_review = generate_review(drama)
                    self.log(f"AI影评（{len(ai_review)}字）：{ai_review}", "SUCCESS")

                    full_text = publisher.compose_text(drama, episode, ai_review)
                    self.log(f"完整文案：{full_text}", "INFO")

                    self.log("正在下载海报...", "INFO")
                    image_path = download_poster(poster, drama)
                    self.log(f"海报已下载: {image_path}", "SUCCESS")

                    max_retries = self.config.get("max_retries", 3)
                    success = publisher.publish(full_text, image_path, max_retries)

                    if success:
                        # ★ 发布评论（夸+度）
                        baidu = self.baidu_link_var.get().strip()
                        comment_lines = self._build_comment_lines(pan, baidu)
                        for line in comment_lines:
                            self.log(f"正在发送评论: {line}", "INFO")
                            publisher.comment_on_post(line, max_retries)

                        self.log(f"🎉 《{drama}》发布完成！", "SUCCESS")
                        # ★ 标记已发布
                        self._mark_posted(drama)
                    else:
                        self.log(f"《{drama}》发布失败，跳过", "ERROR")

                    cleanup_temp(drama)

                except Exception as e:
                    self.log(f"《{drama}》处理异常: {e}", "ERROR")

                # 等待间隔
                if i < len(self.tasks) - 1 and not self.stop_flag:
                    wait_min = self.interval_var.get()
                    self.log(f"⏳ 等待 {wait_min} 分钟后发布下一条...", "INFO")
                    for _ in range(wait_min * 60):
                        if self.stop_flag or self.is_paused:
                            break
                        time.sleep(1)

            self.log("🏁 批量发布完成！", "SUCCESS")
            self.status_var.set("批量发布完成")

        except Exception as e:
            self.log(f"批量发布异常: {e}", "ERROR")
            self.status_var.set(f"异常: {e}")
        finally:
            publisher.close()
            self._set_buttons_running(False)
            self.log("浏览器已关闭", "INFO")


def main():
    root = tk.Tk()
    app = WeiboPublisherGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
