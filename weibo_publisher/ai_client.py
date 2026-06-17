"""
AI客户端模块
调用OpenAI兼容API生成影评文案，要求像真人写的微博/小红书风格
"""

import json
from pathlib import Path
from openai import OpenAI


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_review(drama_name: str) -> str:
    """
    根据剧名调用AI生成影评

    要求：
    - 100字左右
    - 口语化，像真人发微博/小红书的风格
    - 带3个emoji
    - 有具体感受，不要太笼统
    - 不加任何话题标签
    """
    config = load_config()

    client = OpenAI(
        api_key=config["api_key"],
        base_url=config["api_base"],
    )

    # ★ 精心设计的Prompt：模仿真人影评风格
    prompt = f"""你是一个普通观众，刚看完《{drama_name}》，想在微博上分享观后感。

要求：
1. 写100字左右的观后感，口语化，像朋友聊天一样自然
2. 要提到具体的感受、某个场景或角色，不要太笼统
3. 带3个emoji，分散在文中
4. 语气要真实，可以有吐槽、感叹、安利的口吻
5. 不要用"这部剧"开头，用更自然的开头方式
6. 绝对不要加任何话题标签（不要加#号）
7. 不要写"观后感""影评"这类词，就像在跟朋友安利
8. 参考小红书/豆瓣上真人用户写剧评的风格

直接输出正文，不要有任何前缀、标题、引号。"""


    response = client.chat.completions.create(
        model=config["model"],
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=300,  # ★ 增大token数，确保能输出100字
        temperature=0.9,  # ★ 提高温度，让输出更自然多样
    )

    review = response.choices[0].message.content.strip()

    # 去除可能的引号包裹
    if review.startswith('"') and review.endswith('"'):
        review = review[1:-1]
    if review.startswith("'") and review.endswith("'"):
        review = review[1:-1]
    # 去除可能的前缀
    for prefix in ["答：", "回复：", "正文：", "文案："]:
        if review.startswith(prefix):
            review = review[len(prefix):]

    return review


if __name__ == "__main__":
    result = generate_review("帮帮我托德")
    print(f"生成的影评（{len(result)}字）：{result}")
