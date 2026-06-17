# YLFile微博发布工具

🎬 AI生成影评 + 浏览器嵌入界面 + 自动发布微博 + 评论区发网盘链接

---

## 环境要求

- Python 3.8+
- Chrome 浏览器
- 网络正常

## 安装

```bash
cd weibo_publisher
pip install -r requirements.txt
```

## 启动

```bash
python main.py
```

## 功能

- **嵌入浏览器**：浏览器直接显示在软件界面中，不弹新窗口
- **AI影评**：输入剧名自动生成100字小红书/豆瓣风格影评
- **双网盘评论**：发布后评论区自动发送夸克 + 百度链接
- **记忆功能**：记住上次发布的剧名，防止重复发布
- **批量发布**：CSV导入多条任务，按间隔自动发布
- **暂停/继续**：随时暂停或停止批量发布

## 界面说明

软件界面分为：
- **顶部**：输入表单（剧名、集数、海报URL、网盘链接、按钮）
- **底部标签页**：
  - 🌐 浏览器 — 直接在界面内操作微博
  - 📜 日志 — 实时发布日志

## 配置

编辑 `config.json`：

```json
{
  "api_base": "https://api.deepseek.com/v1",
  "api_key": "sk-你的密钥",
  "model": "deepseek-chat",
  "default_interval": 5,
  "max_retries": 3,
  "weibo_url": "https://weibo.com"
}
```

## 文件说明

| 文件 | 说明 |
|------|------|
| main.py | 程序入口 |
| app.py | 主应用（界面+浏览器+发布逻辑） |
| ai_client.py | AI影评生成 |
| downloader.py | 海报下载 |
| config.json | 配置 |
| memory.json | 记忆（自动生成） |
| cookie.pkl | Cookie（自动生成） |
| log.txt | 日志（自动生成） |
