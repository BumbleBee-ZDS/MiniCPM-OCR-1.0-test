#!/usr/bin/env python3
"""通过 Ollama API 调用 MiniCPM-OCR 1.0 解析图片 / PDF 页面。

用法示例：
    python ocr.py test_page.png
    python ocr.py test_page.png -p table
    python ocr.py test_page.png -p formula
    python ocr.py test_page.png --fields "发票号码,金额"
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "openbmb/minicpm-ocr1.0"

# MiniCPM-OCR 1.0 官方支持的任务提示词（见模型卡 Prompts 表）
PROMPTS = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
    "seal": "Seal Recognition:",
    "chart": "Chart to Table:",
}

KIE_TEMPLATE = (
    'Extract the {fields}. Format the output as a JSON object with keys: {fields}. '
    'If an item is not in the image, use "###".'
)


def build_kie_prompt(fields: list[str]) -> str:
    """按官方模板拼接关键信息抽取（KIE）提示词。"""
    quoted = ", ".join(f'"{f}"' for f in fields)
    return KIE_TEMPLATE.format(fields=quoted)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiniCPM-OCR 1.0 (Ollama) 命令行调用")
    parser.add_argument("image", type=Path, help="待识别图片路径（PDF 请先转成图片）")
    parser.add_argument(
        "-p",
        "--prompt",
        default="text",
        help=f"任务名 {', '.join(PROMPTS)}，或直接给完整提示词（默认 text）",
    )
    parser.add_argument(
        "--fields",
        default="",
        help='KIE 抽取字段，逗号分隔，例如 "发票号码,金额"；给出后优先于 -p',
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama 模型名")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama 服务地址")
    parser.add_argument("--stream", action="store_true", help="流式输出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.image.is_file():
        print(f"图片不存在: {args.image}", file=sys.stderr)
        return 1

    if args.fields:
        prompt = build_kie_prompt([f.strip() for f in args.fields.split(",") if f.strip()])
    else:
        prompt = PROMPTS.get(args.prompt, args.prompt)

    payload = {
        "model": args.model,
        "prompt": prompt,
        "images": [base64.b64encode(args.image.read_bytes()).decode()],
        "stream": args.stream,
        # OCR 场景需要确定性输出，温度置 0
        "options": {"temperature": 0},
    }

    try:
        if not args.stream:
            resp = requests.post(f"{args.host}/api/generate", json=payload, timeout=600)
            resp.raise_for_status()
            print(resp.json()["response"])
            return 0

        with requests.post(
            f"{args.host}/api/generate", json=payload, stream=True, timeout=600
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                print(chunk.get("response", ""), end="", flush=True)
                if chunk.get("done"):
                    print()
                    break
    except requests.RequestException as exc:
        detail = getattr(exc.response, "text", "")
        print(f"请求失败: {exc}{(' -> ' + detail) if detail else ''}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
