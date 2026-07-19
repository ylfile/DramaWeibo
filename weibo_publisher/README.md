# YLFile微博发布工具 v4.17

🎬 AI生成影评 + 自动发布微博 + 评论区发网盘链接 + 模板自定义

---

## 环境要求

- Python 3.8+
- Chrome 浏览器 + ChromeDriver（版本匹配）
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

## 打包为 exe

```bash
python -m PyInstaller --onefile --noconsole --name=YLFile main.py
```

输出：`dist/YLFile.exe`

## 功能

- **AI影评**：输入剧名自动生成100字口语化影评（DeepSeek API）
- **模板自定义**：正文模板（单季/多季）、评论模板、AI提示词均可在软件内修改并保存
- **双网盘评论**：发布后评论区自动发送夸克 + 百度链接（CDP注入，支持非BMP字符）
- **自动发布**：填入数据后一键自动发布，支持暂停/停止
- **实时监听**：对接飞书表格 / Google Sheets / 本地CSV，自动读取新数据发布
- **数据源**：支持飞书表格、Google Sheets、本地CSV三种数据源
- **记忆功能**：记住上次发布的剧名、起始行，防止重复发布
- **浏览器复用**：共享浏览器会话，减少登录次数
- **智能重试**：发布失败自动重试，浏览器启动失败自动停止循环

## 界面说明

软件界面分为：
- **上方左侧**：发布内容（剧名、原名、年份、又名、类型、季数、集数、海报URL、网盘链接、标签）
- **上方中间**：模板设置（正文单季/多季模板、评论模板、AI提示词设置）
- **上方右侧**：API设置 + 运行日志
- **中间**：操作按钮（一键发布、自动发布、实时监听）
- **下方**：数据源设置（飞书表格 / Google Sheets / 本地CSV）

## 模板变量

正文模板可用变量：
| 变量 | 说明 |
|------|------|
| `{剧名}` | 剧名 |
| `{原名}` | 原名（英文名） |
| `{年份}` | 年份 |
| `{又名}` | 又名 |
| `{类型}` | 类型 |
| `{集数}` | 集数（原始值，如 39、2/39） |
| `{季数}` | 季数（原始值，如 3） |
| `{AI影评}` | AI生成的影评内容 |
| `{标签}` | 标签（默认：电视剧） |

评论模板可用变量：
| 变量 | 说明 |
|------|------|
| `{链接}` | 网盘链接 |

AI提示词可用变量：
| 变量 | 说明 |
|------|------|
| `{剧名}` | 剧名 |
| `{原名}` | 原名 |
| `{年份}` | 年份 |

## 配置

首次运行自动生成 `config.json`，也可手动编辑：

```json
{
  "api_base": "https://api.deepseek.com/v1",
  "api_key": "sk-你的密钥",
  "model": "deepseek-chat",
  "default_interval": 5,
  "max_retries": 3,
  "weibo_url": "https://weibo.com",
  "post_template": "#{剧名}# {原名} {年份}\n又名：{又名}\n类型：{类型}\n👇👇👇全{集数}集见评👇👇👇\n{AI影评}#电视剧#",
  "post_template_multi": "#{剧名}# {原名}\n又名：{又名}\n类型：{类型}\n👇👇👇1-{季数}季见评👇👇👇\n{AI影评}#电视剧#",
  "comment_quark_template": "K👉{链接}",
  "comment_baidu_template": "D👉{链接}",
  "ai_prompt": "你是微博影视博主..."
}
```

## 文件说明

| 文件 | 说明 |
|------|------|
| main.py | 程序入口 |
| app.py | 主应用（PyQt5界面 + 发布逻辑 + AI影评） |
| publisher.py | Selenium浏览器自动化（发布、评论） |
| ai_client.py | AI影评生成（OpenAI兼容API） |
| downloader.py | 海报图片下载 |
| gui.py | 备用Tkinter界面（未使用） |
| config.json | 配置（运行时自动生成） |
| memory.json | 记忆（运行时自动生成） |
| cookie.pkl | 微博Cookie（运行时自动生成） |

## 技术栈

- GUI：PyQt5
- 浏览器自动化：Selenium + ChromeDriver（CDP协议注入）
- AI影评：OpenAI兼容API（DeepSeek模型）
- 数据源：飞书API / Google Sheets API / 本地CSV
- 打包：PyInstaller（--onefile --noconsole）
