#!/usr/bin/env python3
"""图像方向自动纠正 —— 给 MiniCPM-OCR 做前置处理。

模型本身不具备方向对齐能力（见 test_rotation.py 的实测），
所以识别前必须先转正。本脚本分三步：

1. EXIF：按 EXIF Orientation 直接纠正（手机拍摄的常见情况）。
2. 形态学判向：比较行/列墨量投影的高频能量，判断文本是横排还是竖排，
   据此把候选缩小到 {0°, 180°} 或 {90°, 270°}。
3. 二选一：对两个候选各跑一次 KIE，按「字段取值是否合理」打分选优。

用法：
    python orientation.py 图片.jpg                 # 检测并输出 <原名>_upright.jpg
    python orientation.py 图片.jpg --no-model      # 只用启发式（0/180 歧义时取 0°）
    python orientation.py 图片.jpg --fields 发票号码,金额
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from recognize_invoice import INVOICE_FIELDS, MODEL, ask, kie_prompt


# ---------------------------------------------------------------- 基础工具

def _ink_profile(image: Image.Image, size: int = 800) -> tuple[np.ndarray, np.ndarray]:
    gray = image.convert("L").resize((size, size))
    ink = (255.0 - np.asarray(gray, dtype=float)) / 255.0
    return ink.sum(axis=1), ink.sum(axis=0)


def horizontal_score(image: Image.Image) -> float:
    """>1 表示文本行横向排列（正常排版）；<1 表示整幅图被转了 90°/270°。"""
    rows, cols = _ink_profile(image)
    hf_row = np.abs(np.diff(rows)).sum() / (rows.sum() + 1e-6)
    hf_col = np.abs(np.diff(cols)).sum() / (cols.sum() + 1e-6)
    return float(hf_row / (hf_col + 1e-6))


def rotate(image: Image.Image, degrees: int) -> Image.Image:
    """顺时针旋转 degrees 度（PIL 的 rotate 是逆时针，故取负）。"""
    return image.rotate(-degrees, expand=True)


def encode_pil(image: Image.Image, quality: int = 95) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- 字段合理性

CURRENCY_RE = re.compile(r"^[¥￥]?\s*\d[\d,]*(\.\d+)?$")
CN_NUM_RE = re.compile(r"^[零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆角分整正⊗☒ ]+$")


def plausible(field: str, value: str) -> bool:
    """粗略判断字段取值是否符合常识，用于给候选方向打分（可按业务扩展）。"""
    v = str(value).strip()
    if v in ("", "###", "None", "null") or "*" in v or "\n" in v:
        return False
    if "号码" in field or "编号" in field:
        return bool(re.fullmatch(r"[0-9A-Za-z\-]{3,25}", v))
    if "日期" in field or "时间" in field:
        return bool(re.search(r"\d{4}\s*[年\-/.]", v))
    if "识别号" in field or "代码" in field or "税号" in field:
        return bool(re.fullmatch(r"[0-9A-Z]{6,25}", v))
    if "大写" in field:
        return bool(CN_NUM_RE.fullmatch(v)) and v.endswith(("整", "正"))
    if any(k in field for k in ("金额", "税额", "合计", "单价", "价税")):
        return bool(CURRENCY_RE.fullmatch(v))
    if "名称" in field:
        return 2 <= len(v) <= 40
    if field.endswith("人"):
        return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", v))
    return len(v) <= 50


def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except ValueError:
        return {}


def kie_score(image: Image.Image, fields: list[str], model: str, host: str) -> float:
    data = parse_json(ask(kie_prompt(fields), encode_pil(image), model, host))
    if not data:
        return 0.0
    return sum(plausible(f, data.get(f, "")) for f in fields) / len(fields)


# ---------------------------------------------------------------- 主流程

def detect_upright(
    path: Path,
    model: str = MODEL,
    host: str = "http://127.0.0.1:11434",
    fields: list[str] | None = None,
    use_model: bool = True,
) -> tuple[Image.Image, dict]:
    """返回 (转正后的图像, 诊断信息)。"""
    raw = Image.open(path)
    exif_angle = int(raw.getexif().get(274, 1) or 1)
    image = ImageOps.exif_transpose(raw)          # 步骤 1：EXIF

    score_h = horizontal_score(image)             # 步骤 2：横排 / 竖排
    vertical = score_h < 1.0
    candidates = [90, 270] if vertical else [0, 180]

    info = {
        "exif_orientation": exif_angle,
        "horizontal_score": round(score_h, 3),
        "layout": "vertical" if vertical else "horizontal",
        "candidates": candidates,
    }

    # 步骤 3：两个候选之间二选一
    if not use_model:
        best = candidates[0]
        info["method"] = "heuristic"
    else:
        fields = fields or INVOICE_FIELDS
        scores = {}
        for deg in candidates:
            cand = image if deg == 0 else rotate(image, deg)
            scores[deg] = round(kie_score(cand, fields, model, host), 3)
        # 打平时偏向原始方向，避免无谓旋转
        best = max(scores, key=lambda d: (scores[d], d in (0, 90)))
        info["method"] = "heuristic+kie"
        info["kie_scores"] = scores

    info["rotate"] = best
    upright = image if best == 0 else rotate(image, best)
    return upright, info


def main() -> int:
    p = argparse.ArgumentParser(description="检测并纠正图像方向（OCR 前置处理）")
    p.add_argument("image")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--host", default="http://127.0.0.1:11434")
    p.add_argument("--fields", default=",".join(INVOICE_FIELDS), help="用于打分的字段，逗号分隔")
    p.add_argument("--no-model", action="store_true", help="只用启发式，不调用模型")
    p.add_argument("--out", default=None, help="输出路径，默认 <原名>_upright.jpg")
    args = p.parse_args()

    src = Path(args.image)
    if not src.is_file():
        raise SystemExit(f"图片不存在: {src.resolve()}")

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    upright, info = detect_upright(src, args.model, args.host, fields, use_model=not args.no_model)

    out = Path(args.out) if args.out else src.with_name(f"{src.stem}_upright.jpg")
    upright.convert("RGB").save(out, quality=95)

    print(f"EXIF Orientation = {info['exif_orientation']}")
    print(f"横排评分(HF_row/HF_col) = {info['horizontal_score']}  -> {info['layout']}")
    if "kie_scores" in info:
        print("候选方向字段合理性:", {f"{k}°": v for k, v in info["kie_scores"].items()})
    print(f"判定旋转 {info['rotate']}°（{info['method']}）-> {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
