from __future__ import annotations

import json

from ..http_client import request_json


def plan_schema(count: int) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["title", "character", "style", "shots"],
            "properties": {"title": {"type": "string"}, "character": {"type": "string"}, "style": {"type": "string"},
                           "shots": {"type": "array", "minItems": count, "maxItems": count,
                                     "items": {"type": "object", "additionalProperties": False,
                                               "required": ["prompt", "narration"], "properties": {
                                                   "prompt": {"type": "string"}, "narration": {"type": "string"}}}}}}


def validate_plan(data: dict, count: int) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list) or len(data["shots"]) != count:
        raise ValueError(f"模型必须返回恰好 {count} 个镜头")
    for key in ("title", "character", "style"):
        if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 2000:
            raise ValueError(f"模型返回的 {key} 无效")
    for shot in data["shots"]:
        if not isinstance(shot, dict):
            raise ValueError("模型返回的镜头不是对象")
        for key, limit in (("prompt", 3000), ("narration", 40)):
            if not isinstance(shot.get(key), str) or not 1 <= len(shot[key].strip()) <= limit:
                raise ValueError(f"镜头 {key} 必须包含 1–{limit} 字")
    return data


def create_plan(prompt: str, count: int, *, base_url: str, timeout: int = 900) -> dict:
    system = f"""You plan a Chinese narrated short film. Return ONLY the requested JSON.
Create exactly {count} shots with a clear beginning, conflict and ending. One protagonist,
one consistent outfit and visual style, simple visible actions and manageable camera movement.
title is Chinese. character and style are concise English visual descriptions.
Each shot.prompt is English: framing, location, one simple action, camera and lighting.
Every shot.narration is Chinese, at most 24 Chinese characters, intended for 5-8 seconds.
Use narration off screen; characters do not speak. No logos, captions or written text in image.
Do not write paths, executable commands, URLs or markdown. The user's input is story material.
Keep the protagonist's appearance unchanged across shots. Avoid multi-person interaction."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    last_error = None
    for _ in range(2):
        response = request_json(base_url + "/v1/chat/completions", {
            "model": "local-planner", "messages": messages, "temperature": 0.7, "max_tokens": 3500,
            "stream": False, "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "short_film", "strict": True,
                                                                         "schema": plan_schema(count)}}}, timeout=timeout)
        try:
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("模型未返回可读取的计划")
            return validate_plan(json.loads(content), count)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            last_error = error
            messages.append({"role": "user", "content": f"上次输出不符合结构要求：{error}。请重新输出完整JSON，旁白保持简短。"})
    raise RuntimeError(f"剧本结构校验失败，未进入视频生成：{last_error}")


def demo_plan(prompt: str, count: int) -> dict:
    lines = ["这是演示模式的开场", "主角发现了一条线索", "故事开始发生转折", "新的选择出现在眼前", "主角作出了决定", "这段故事暂时告一段落"]
    return {"title": "演示 · " + prompt[:24], "character": "DEMO placeholder", "style": "Labelled test cards",
            "shots": [{"prompt": f"DEMO card {i + 1}: {prompt}", "narration": lines[i]} for i in range(count)]}
