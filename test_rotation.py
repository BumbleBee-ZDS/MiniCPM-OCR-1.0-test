#!/usr/bin/env python3
"""测试 MiniCPM-OCR 1.0 对旋转图像的鲁棒性。

把同一张图分别旋转 0/90/180/270 度，各跑一次「文本识别 + 关键信息抽取」，
用与 0° 结果的文本相似度、KIE 字段命中率来衡量准确度。

用法：
    python test_rotation.py                       # 用默认发票图做四方向对比
    python test_rotation.py other.jpg
    python test_rotation.py --auto other.jpg      # 只做方向自动检测
    python test_rotation.py --fields 发票号码,金额
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import time
from pathlib import Path

from PIL import Image

from recognize_invoice import INVOICE_FIELDS, ask, encode_image, kie_prompt

DEFAULT_IMAGE = "图片_20261031030910_20_1.jpg"
OUT_DIR = Path("rotation_test")


def rotate(path: Path, degrees: int, out_dir: Path = OUT_DIR) -> Path:
    """顺时针旋转 degrees 度并另存，返回新文件路径。"""
    img = Image.open(path)
    # PIL 的 rotate 是逆时针，用相反角度实现顺时针
    img = img.rotate(-degrees, expand=True)
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / f"{path.stem}_rot{degrees:03d}.jpg"
    img.convert("RGB").save(dest, quality=95)
    return dest


def normalize(text: str) -> str:
    """只保留中文/字母/数字，便于比较不同方向下的识别结果。"""
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except ValueError:
        return {}


def valid_fields(data: dict, fields: list[str]) -> int:
    """返回有效（非空且非 "###"）的字段个数。"""
    return sum(1 for f in fields if str(data.get(f, "")).strip() not in ("", "###", "None"))


def run_once(image: Path, fields: list[str], model: str, host: str) -> dict:
    img = encode_image(image)
    t0 = time.time()
    text = ask("Text Recognition:", img, model, host)
    t1 = time.time()
    data = parse_json(ask(kie_prompt(fields), img, model, host))
    t2 = time.time()
    return {
        "text": text,
        "kie": data,
        "hits": valid_fields(data, fields),
        "t_text": t1 - t0,
        "t_kie": t2 - t1,
    }


def detect_orientation(image: Path, model: str, host: str) -> int:
    """方向自动检测：复用 orientation.py 的策略（EXIF + 形态学 + KIE 打分）。

    注意：实测「直接问模型是否颠倒」不可靠（0°/180° 都答 Yes），
    也不要用纯文本长度做启发式（四种方向字数接近），必须用这里的组合策略。
    """
    from orientation import detect_upright

    _, info = detect_upright(image, model=model, host=host)
    print(
        f"EXIF={info['exif_orientation']}  HF={info['horizontal_score']}({info['layout']})  "
        f"候选={info['candidates']}  打分={info.get('kie_scores')}  -> 旋转 {info['rotate']}°"
    )
    return info["rotate"]


def main() -> int:
    p = argparse.ArgumentParser(description="测试模型对旋转图像的识别能力")
    p.add_argument("image", nargs="?", default=DEFAULT_IMAGE)
    p.add_argument("--model", default="openbmb/minicpm-ocr1.0")
    p.add_argument("--host", default="http://127.0.0.1:11434")
    p.add_argument("--rotations", default="0,90,180,270")
    p.add_argument("--fields", default=",".join(INVOICE_FIELDS))
    p.add_argument("--auto", action="store_true", help="只做方向自动检测")
    p.add_argument("--out", default="rotation_test/report.md")
    args = p.parse_args()

    image = Path(args.image)
    if not image.is_file():
        raise SystemExit(f"图片不存在: {image.resolve()}")
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]

    if args.auto:
        detect_orientation(image, args.model, args.host)
        return 0

    rotations = [int(x) for x in args.rotations.split(",")]
    results: dict[int, dict] = {}
    for deg in rotations:
        path = image if deg == 0 else rotate(image, deg)
        print(f"[{deg:>3}°] 识别中 ... ({path.name})", flush=True)
        r = run_once(path, fields, args.model, args.host)
        results[deg] = r
        print(f"       文本 {len(normalize(r['text']))} 字, 字段命中 {r['hits']}/{len(fields)}, "
              f"{r['t_text'] + r['t_kie']:.1f}s", flush=True)

    baseline = results[0]
    rows = ["| 旋转 | 有效字符 | 与0°文本相似度 | 字段命中 | 字段与0°一致 | 用时 |",
            "| :--: | :------: | :------------: | :------: | :----------: | :--: |"]
    detail = []
    for deg in rotations:
        r = results[deg]
        sim = similarity(baseline["text"], r["text"])
        same = sum(1 for f in fields if str(r["kie"].get(f, "")).strip() == str(baseline["kie"].get(f, "")).strip())
        rows.append(f"| {deg}° | {len(normalize(r['text']))} | {sim:.3f} | "
                    f"{r['hits']}/{len(fields)} | {same}/{len(fields)} | {r['t_text'] + r['t_kie']:.1f}s |")
        detail.append(f"### {deg}°\n\n```text\n{r['text'].strip()}\n```\n\n"
                      f"```json\n{json.dumps(r['kie'], ensure_ascii=False, indent=2)}\n```\n")

    report = "\n".join(["# 旋转鲁棒性测试", "", *rows, "", *detail])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print("\n" + "\n".join(rows))
    print(f"\n详细结果: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
