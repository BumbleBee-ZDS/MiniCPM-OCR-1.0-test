#!/usr/bin/env python3
"""生成一张用于验证 MiniCPM-OCR 1.0 识别效果的测试文档图片。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
OUT_PATH = Path(__file__).with_name("test_page.png")

W, H = 1000, 760


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def main() -> None:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # 标题
    d.text((60, 45), "MiniCPM-OCR 1.0 测试文档", font=font(38), fill="black")
    d.line([(60, 100), (940, 100)], fill="black", width=2)

    # 正文（中英混排）
    body = [
        "MiniCPM-OCR 1.0 是一个 1.3B 参数的端侧 OCR 解析模型，支持中文与",
        "English documents, tables, formulas, charts and seals.",
        "它在 Real5-OmniDocBench 上取得了 93.68 的分数。",
    ]
    y = 125
    for line in body:
        d.text((60, y), line, font=font(22), fill="black")
        y += 38

    # 表格
    y += 20
    d.text((60, y), "表 1：模型参数对比", font=font(22), fill="black")
    y += 40
    cols = [(60, 240), (240, 480), (480, 700), (700, 940)]
    rows = [
        ["模型", "参数量", "语种", "备注"],
        ["MiniCPM-OCR 1.0", "1.3B", "中/英", "文档解析"],
        ["PaddleOCR-VL-1.6", "-", "多语种", "对比基线"],
    ]
    row_h = 42
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            x0, x1 = cols[c]
            d.rectangle([x0, y, x1, y + row_h], outline="black", width=1)
            d.text((x0 + 10, y + 9), text, font=font(20), fill="black")
        y += row_h

    # 公式
    y += 30
    d.text((60, y), "公式：y = ax² + bx + c，其中 a ≠ 0。", font=font(24), fill="black")

    # 关键信息
    y += 55
    d.text((60, y), "发票号码：INV-2026-1031    金额：￥1,280.00", font=font(22), fill="black")

    img.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
