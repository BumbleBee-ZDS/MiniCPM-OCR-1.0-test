#!/usr/bin/env python3
"""调用本地 MiniCPM-OCR 1.0（Ollama）识别发票图片。

对同一张图做三件事：
  1. 整页文本识别（Text Recognition:）
  2. 表格识别（Table Recognition:，输出 OTSL 结构，再转成 HTML 表格）
  3. 关键信息抽取（KIE，按字段返回 JSON）

用法：
    python recognize_invoice.py                                  # 默认识别本目录发票图
    python recognize_invoice.py 图片_20261031030910_20_1.jpg
    python recognize_invoice.py other.jpg --model openbmb/minicpm-ocr1.0:q8_0
    python recognize_invoice.py other.jpg --out result.md
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from collections import defaultdict
from html import escape
from pathlib import Path

import requests

HOST = "http://127.0.0.1:11434"
MODEL = "openbmb/minicpm-ocr1.0"
DEFAULT_IMAGE = "图片_20261031030910_20_1.jpg"

# 发票常用字段，按需增减即可（字段名会原样出现在提示词和 JSON key 中）
INVOICE_FIELDS = [
    "发票号码",
    "开票日期",
    "购买方名称",
    "购买方纳税人识别号",
    "销售方名称",
    "销售方纳税人识别号",
    "合计金额",
    "合计税额",
    "价税合计(大写)",
    "价税合计(小写)",
    "开票人",
]

# 官方 KIE 提示词模板（模型卡写法）
KIE_TEMPLATE = (
    'Extract the {fields}. Format the output as a JSON object with keys: {fields}. '
    'If an item is not in the image, use "###".'
)

OTSL_TOKEN = re.compile(r"<(fcel|lcel|ucel|xcel|ecel|nl)>")


def encode_image(path: Path) -> str:
    """图片 -> base64 字符串（Ollama images 字段要求）。"""
    return base64.b64encode(path.read_bytes()).decode()


def ask(prompt: str, image_b64: str, model: str = MODEL, host: str = HOST) -> str:
    """发送一次图文请求，返回模型输出文本。"""
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        # OCR 场景用贪心解码，保证结果稳定
        "options": {"temperature": 0},
    }
    resp = requests.post(f"{host}/api/generate", json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()["response"]


def kie_prompt(fields: list[str]) -> str:
    quoted = ", ".join(f'"{f}"' for f in fields)
    return KIE_TEMPLATE.format(fields=quoted)


def otsl_to_html(otsl: str) -> str:
    """把模型输出的 OTSL 表格结构转换成 HTML <table>。

    OTSL 单元格标记：
      fcel 普通单元格  lcel 与左侧合并  ucel 与上方合并
      xcel 同时与左上合并              ecel 空单元格
      nl   换行
    """
    marks = list(OTSL_TOKEN.finditer(otsl))
    tokens: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(otsl)
        tokens.append((m.group(1), otsl[m.end() : end].strip()))

    rows: dict[int, list[dict]] = defaultdict(list)
    grid: dict[tuple[int, int], dict] = {}
    r = c = 0
    for kind, text in tokens:
        if kind == "nl":
            r, c = r + 1, 0
            continue
        while (r, c) in grid:  # 跳过被上方 rowspan 占用的列
            c += 1

        cell = {"text": text, "colspan": 1, "rowspan": 1}
        if kind == "fcel":
            rows[r].append(cell)
            grid[(r, c)] = cell
        elif kind == "ecel":
            rows[r].append({"text": "", "colspan": 1, "rowspan": 1})
            grid[(r, c)] = rows[r][-1]
        elif kind == "lcel":  # 并入左侧单元格
            left = grid.get((r, c - 1))
            if left:
                left["colspan"] += 1
                grid[(r, c)] = left
            else:
                rows[r].append(cell)
                grid[(r, c)] = cell
        else:  # ucel / xcel：并入上方单元格
            above = next((grid[(rr, c)] for rr in range(r - 1, -1, -1) if (rr, c) in grid), None)
            if above is None:
                rows[r].append(cell)
                grid[(r, c)] = cell
            else:
                above["rowspan"] += 1
                if kind == "xcel":
                    above["colspan"] += 1
                grid[(r, c)] = above
        c += 1

    out = ["<table>"]
    for r in sorted(rows):
        out.append("  <tr>")
        for cell in rows[r]:
            attrs = ""
            if cell["colspan"] > 1:
                attrs += f' colspan="{cell["colspan"]}"'
            if cell["rowspan"] > 1:
                attrs += f' rowspan="{cell["rowspan"]}"'
            out.append(f"    <td{attrs}>{escape(cell['text'])}</td>")
        out.append("  </tr>")
    out.append("</table>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniCPM-OCR 1.0 发票识别示例")
    parser.add_argument("image", nargs="?", default=DEFAULT_IMAGE, help="发票图片路径")
    parser.add_argument("--model", default=MODEL, help="Ollama 模型名")
    parser.add_argument("--host", default=HOST, help="Ollama 服务地址")
    parser.add_argument("--out", default="发票_识别结果.md", help="结果保存路径（Markdown）")
    args = parser.parse_args()

    image = Path(args.image)
    if not image.is_file():
        raise SystemExit(f"图片不存在: {image.resolve()}")

    print(f"[1/3] 读取图片 {image.name} ({image.stat().st_size / 1024:.0f} KB)")
    img = encode_image(image)

    print("[2/3] 文本识别 + 表格识别 ...")
    text = ask("Text Recognition:", img, args.model, args.host)
    otsl = ask("Table Recognition:", img, args.model, args.host)
    table_html = otsl_to_html(otsl)

    print("[3/3] 关键信息抽取 ...")
    raw_kie = ask(kie_prompt(INVOICE_FIELDS), img, args.model, args.host)
    try:
        fields = json.loads(raw_kie[raw_kie.index("{") : raw_kie.rindex("}") + 1])
    except ValueError:
        fields = {"_raw": raw_kie}

    markdown = "\n\n".join(
        [
            f"# 发票识别结果：{image.name}",
            "## 关键信息（KIE）\n\n```json\n" + json.dumps(fields, ensure_ascii=False, indent=2) + "\n```",
            "## 整页文本\n\n```text\n" + text.strip() + "\n```",
            "## 表格（OTSL → HTML）\n\n" + table_html,
            "## 原始 OTSL\n\n```xml\n" + otsl.strip() + "\n```",
        ]
    )
    Path(args.out).write_text(markdown, encoding="utf-8")

    print("\n===== 关键信息 =====")
    print(json.dumps(fields, ensure_ascii=False, indent=2))
    print(f"\n完整结果已保存: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
