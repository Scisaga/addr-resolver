# qwen_call.py
import os
import time
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

from config import logger, LLM_API_KEY, QWEN_MODEL


# 初始化通义千问客户端（OpenAI 接口格式兼容）
client = OpenAI(
    api_key=LLM_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def call_qwen(prompt: str, model: str = QWEN_MODEL) -> str:
    """
    调用通义千问模型，获取结构化/标准化结果
    :param prompt: 输入的 prompt 内容
    :param model: 使用的模型名称
    :return: 模型返回的文本结果
    """
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个中文地理信息分析助手"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            top_p=1,  # 避免极端值（推荐保留默认或略低）
            presence_penalty=0,  # 控制重复内容，适度增加稳定性
            frequency_penalty=0,  # 减少内容偏离
            n=1, # 只返回一个结果
            seed=42,
            response_format={         # 需要结构化时强烈建议使用
                "type": "json_object"
            },
            extra_body={
                "enable_thinking": False
            }
        )
        end = time.time()
        duration = end - start
        logger.debug(f"模型响应耗时：{duration:.2f} 秒")

        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"通义千问调用失败：{e}")
        return ""