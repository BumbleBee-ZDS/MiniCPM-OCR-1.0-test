# MiniCPM-OCR 1.0 本地部署与使用手册（Ollama）

> 在 **4 GB 显存**的 GTX 1050 Ti 上跑通 MiniCPM-OCR 1.0 的完整记录：安装踩坑、提示词用法、
> 脚本手册、性能实测、方向鲁棒性实验与故障排查。所有数据均为本机实测。

---

## 目录

- [0. 一页速查](#0-一页速查)
- [1. 这是什么](#1-这是什么)
- [2. 环境与版本](#2-环境与版本)
- [3. 三步跑通](#3-三步跑通)
- [4. 安装与升级](#4-安装与升级)
- [5. 模型规格](#5-模型规格)
- [6. 提示词参考](#6-提示词参考)
- [7. 脚本手册](#7-脚本手册)
- [8. 直接调用 API](#8-直接调用-api)
- [9. 性能实测](#9-性能实测)
- [10. 质量边界与陷阱](#10-质量边界与陷阱)
- [11. PDF / 长文档流水线](#11-pdf--长文档流水线)
- [12. 故障排查](#12-故障排查)
- [13. 已知限制](#13-已知限制)
- [14. 参考](#14-参考)

---

## 0. 一页速查

| 我想…… | 命令 |
| :--- | :--- |
| 识别一张图的文字 | `python ocr.py page.png` |
| 识别表格 | `python ocr.py page.png -p table` |
| 识别公式 | `python ocr.py page.png -p formula` |
| 抽字段变 JSON | `python ocr.py page.png --fields "发票号码,金额"` |
| 一张发票全都要 | `python recognize_invoice.py 发票.jpg` |
| 图是歪的/颠倒的 | `python orientation.py 图片.jpg` → 得到 `图片_upright.jpg` |
| 验证模型仍正常 | `python ocr.py test_page.png` |
| 看显存占用 | `ollama ps` |
| 重启服务 | `sudo systemctl restart ollama` |
| 卸载模型 | `ollama rm openbmb/minicpm-ocr1.0` |

---

## 1. 这是什么

MiniCPM-OCR 1.0 是 OpenBMB 发布的 **1.3B 端侧文档解析模型**。它不是"检测框 + 逐行识别"的传统流水线，
而是 **图 + 任务前缀 → 结构化结果** 的生成式解析：

| 能力 | 输出形式 |
| :--- | :--- |
| 正文 / 标题 / 段落 / 阅读顺序 | 纯文本 |
| 表格 | **OTSL** 结构（可无损还原合并单元格） |
| 公式 | LaTeX（行内 / 独立） |
| 印章 | 纯文本 |
| 图表 | OTSL 表格 |
| 关键信息抽取（KIE） | JSON（按你指定的字段） |

模型结构 = **Qwen3.5 语言主干（752M）+ CLIP 视觉投影器（444M）**，合计约 1.3B。
本机使用 `Q4_K_M` 量化（1.4 GB），推理全程在本地 GPU 完成，无网络依赖。

### 目录结构

```
minicpm/
├── README.md                 本文档
├── ocr.py                    通用命令行 OCR（文本/表格/公式/印章/图表/KIE）
├── recognize_invoice.py      发票一键识别：KIE + 全文 + OTSL→HTML
├── orientation.py            方向自动纠正（OCR 前置处理）
├── test_rotation.py          旋转鲁棒性对照实验
├── make_test_page.py         生成中英混排测试页
├── upgrade_ollama.sh         Ollama 升级脚本（sudo，补 minicpm_ocr 投影器支持）
├── test_page.png             测试样张（1000×760）
├── 图片_20261031030910_20_1.jpg   实测发票照片（1704×1279）
├── 发票_识别结果.md           recognize_invoice.py 的输出
└── rotation_test/
    ├── report.md             四方向识别结果与 KIE JSON
    └── *.jpg                 各角度测试图 + 纠正后结果
```

---

## 2. 环境与版本

| 项目 | 实测值 |
| :--- | :--- |
| 操作系统 | Ubuntu 26.04.1 LTS |
| CPU / 内存 | 4 核 / 11 GiB |
| GPU | NVIDIA GeForce GTX 1050 Ti（**4 GB**） |
| 显卡驱动 | 580.178.04（CUDA 13.1） |
| Ollama | **0.40.13**（`systemctl is-active ollama` → active） |
| 模型 | `openbmb/minicpm-ocr1.0:latest`（Q4_K_M，1.4 GB） |
| 模型存储 | `/usr/share/ollama/.ollama/models`（全库 3.9 GB） |
| Python | 3.12.14（conda `pytorch_env`） |
| 依赖 | `requests 2.34.2`、`Pillow 12.3.0`、`numpy 2.5.3`、`pdftoppm` |

脚本只依赖 `requests` + `Pillow`（`orientation.py` 另需 `numpy`），不依赖官方 SDK，方便直接改。

---

## 3. 三步跑通

```bash
# 1) 确认服务在跑
ollama --version                 # 期望 0.40.x
systemctl is-active ollama       # 期望 active

# 2) 拉模型（已装可跳过）
ollama pull openbmb/minicpm-ocr1.0

# 3a) 最简：Ollama CLI 直接跑（路径前加 ./ 或绝对路径）
ollama run openbmb/minicpm-ocr1.0 "Text Recognition: ./test_page.png"

# 3b) 或用脚本（推荐，可指定任务/字段）
python ocr.py test_page.png
```

预期输出（`test_page.png`，实测，注意表格用全角空格分隔、行内公式转成了 LaTeX）：

```text
MiniCPM-OCR 1.0 测试文档
MiniCPM-OCR 1.0 是一个 1.3B 参数的端侧 OCR 解析模型，支持中文与 English documents, tables, formulas, charts and seals。
它在 Real5-OmniDocBench 上取得了 93.68 的分数。
表 1：模型参数对比
模型　参数量　语种　备注
MiniCPM-OCR 1.0　1.3B　中/英　文档解析
PaddleOCR-VL-1.6　-　多语种　对比基线
公式：\( y = ax^{2} + bx + c \)，其中 \( a \neq 0 \)。
发票号码：INV-2026-1031  金额：¥1,280.00
```

---

## 4. 安装与升级

### 4.1 拉取模型

```bash
ollama pull openbmb/minicpm-ocr1.0          # 默认 Q4_K_M
# 其他量化：openbmb/minicpm-ocr1.0:q8_0 / :f16
```

### 4.2 为什么 Ollama 必须 ≥ 0.40

本机原本是 0.35.0，加载时直接失败：

```
Error: load_hparams: unknown projector type: minicpm_ocr_1_0
```

原因：视觉投影器类型 `minicpm_ocr_1_0` 是较新的 GGUF 元数据字段，
旧版内置的 llama.cpp / mtmd 不认识，直接拒绝加载（模型文件本身没问题）。
`grep -a minicpm_ocr /usr/local/lib/ollama/libmtmd.so` 可以确认某个版本是否支持——
0.40.13 有，0.35.0 没有。

### 4.3 升级（`upgrade_ollama.sh`）

```bash
# 1) 下载对应平台包（本机 amd64），注意别放 /tmp（本机 /tmp 是内存盘）
curl -L -o ~/ollama-linux-amd64.tar.zst \
  https://github.com/ollama/ollama/releases/download/v0.40.13/ollama-linux-amd64.tar.zst

# 2) 解压到 ~/ollama-new（约 3.5 GB）
mkdir -p ~/ollama-new && tar --zstd -xf ~/ollama-linux-amd64.tar.zst -C ~/ollama-new

# 3) 执行脚本（会备份旧版本到 /tmp/ollama-backup-<时间戳>）
sudo bash upgrade_ollama.sh
```

脚本做的四件事：**备份旧二进制与 `lib-ollama` → `install` 新二进制到 `/usr/local/bin/ollama`
→ 替换 `/usr/local/lib/ollama` → `systemctl daemon-reload && restart`**，最后打印版本。

> 脚本里 `SRC=/tmp/ollama-new`、`TARBALL=/tmp/ollama-linux-amd64.tar.zst` 是按当时环境写死的，
> 若你换机器执行，先改成实际路径（或直接把解压结果放到 `/tmp/ollama-new`）。
> 备份在 tmpfs 上关机即失效，需要长期保留请 `sudo mv` 到磁盘。

### 4.4 备选方案：hf-mirror + `ollama create`（未在本机验证）

当 `ollama pull` 被网络挡住（见 4.6）时的兜底路径：

```bash
# GGUF 仓库：openbmb/MiniCPM-OCR-1.0-gguf（含 mmproj 视觉投影器）
# 国内镜像：https://hf-mirror.com/openbmb/MiniCPM-OCR-1.0-gguf

cat > Modelfile <<'EOF'
FROM ./MiniCPM-OCR-1.0-Q4_K_M.gguf
FROM ./mmproj-MiniCPM-OCR-1.0-f16.gguf
EOF

ollama create minicpm-ocr-local -f Modelfile
```

文件名以仓库实际内容为准（`.gguf` 与 `mmproj*.gguf` 两个文件都要下）。
好处是不经过 Ollama registry，绕开代理/SSRF 限制。

### 4.5 升级后的验证清单

```bash
ollama --version                                   # 0.40.13
systemctl is-active ollama                         # active
ollama list | grep minicpm                         # 模型在列
ollama run openbmb/minicpm-ocr1.0 "Text Recognition: ./test_page.png"
ollama ps                                          # 推理时应有 100% GPU
```

### 4.6 网络坑：Clash Fake-IP 会让 pull 失败

开启 Clash 的 TUN / Fake-IP 模式时，DNS 对所有域名返回 `198.18.x.x`，
Ollama 的 SSRF 防护会拒绝跳转：

```
Error: max retries exceeded: redirect target not allowed:
"http://...", ... resolves to non-public address "198.18.0.19"
```

处理：**关闭代理后再 pull**（或把 Clash 切到 redir-host 模式）。Ollama 没有关掉该检查的环境变量。

---

## 5. 模型规格

```text
$ ollama show openbmb/minicpm-ocr1.0
  Model
    architecture        qwen35
    parameters          752.17M
    context length      262144
    embedding length    1024
    quantization        Q4_K_M
    template source     gguf_chat_template

  Capabilities
    tools / thinking / completion / vision

  Projector
    architecture        clip
    parameters          443.76M
    embedding length    1152
    dimensions          1024

  Parameters
    num_ctx             16384
```

要点：

- **总参数约 1.2B**（752M 主干 + 444M 投影器），官方称 1.3B，差别在计入口径。
- 原生上下文 **262144**，但 Ollama 默认只加载 `num_ctx=16384`。整页 OCR 输出一般 1k–3k token，
  够用；需要连读多页时可调大（见 8.4，需显存支撑）。
- `vision` capability 说明它接受 `images` 字段；`temperature=0` 是 OCR 场景的正确选择。

### 量化版本怎么选（4 GB 显存参考）

| Tag | 大小 | 显存需求 | 建议 |
| :--- | :--- | :--- | :--- |
| `:latest`（Q4_K_M） | 1.4 GB | ~0.9 GB（实测 875 MB） | 本机首选，精度已够用 |
| `:q8_0` | ~1.5 GB | ~1.6 GB | 含细小字符/公式时更稳，4 GB 也放得下 |
| `:f16` | ~2.8 GB | ~2.9 GB | 4 GB 卡可跑但余量小，易与其他进程冲突 |

---

## 6. 提示词参考

### 6.1 任务前缀表

**提示词必须以官方前缀开头**，模型是按这几种前缀做条件生成的：

| 场景 | 提示词 | 输出格式 | `ocr.py` 别名 |
| :--- | :--- | :--- | :--- |
| 整页 / 段落 / 标题 / 阅读顺序 | `Text Recognition:` | 纯文本 | `-p text`（默认） |
| 表格 | `Table Recognition:` | OTSL | `-p table` |
| 独立公式 | `Formula Recognition:` | LaTeX | `-p formula` |
| 行内公式（`$...$`） | `Text Recognition:` | 含 LaTeX 的文本 | — |
| 印章 | `Seal Recognition:` | 纯文本 | `-p seal` |
| 图表 | `Chart to Table:` | OTSL | `-p chart` |
| 关键信息抽取 | 见 6.3 模板 | JSON | `--fields "A,B"` |

> 实测教训：自造前缀（例如 `Key Information Extraction:`）会返回**空输出**。
> 前缀写错不会报错，只会静默返回空字符串——排查时先怀疑这里。

### 6.2 表格输出：OTSL 是什么

`Table Recognition:` 返回的是 **OTSL**（Open Table Structure Language），
用标记表示合并关系，比 HTML 更紧凑、也不会出现标签错配：

| 标记 | 含义 |
| :--- | :--- |
| `<fcel>文本` | 新单元格（full cell），后跟该格文本 |
| `<lcel>` | 与**左侧**单元格合并 |
| `<ucel>` | 与**上方**单元格合并 |
| `<xcel>` | 同时与左、上合并（跨行跨列） |
| `<ecel>` | 空单元格（保留位置） |
| `<nl>` | 换行，开始新的一行 |

实测输出（`test_page.png`）：

```xml
<otsl><fcel>模型<fcel>参数量<fcel>语种<fcel>备注<nl>
<fcel>MiniCPM-OCR 1.0<fcel>1.3B<fcel>中/英<fcel>文档解析<nl>
<fcel>PaddleOCR-VL-1.6<fcel>-<fcel>多语种<fcel>对比基线<nl></otsl>
```

发票里的跨行合并（购买方/销售方两栏各占两行）：

```xml
<fcel>购买方信息<fcel>名称：限公司<lcel><lcel><fcel>销售方信息<fcel>名称：重庆限公司<lcel><lcel><lcel><nl>
<ucel><fcel>统一社会信用代码/纳税人识别号：91330<lcel><lcel><ucel><fcel>…91500<lcel><lcel><lcel><nl>
```

把 OTSL 还原成 HTML 表格用 `recognize_invoice.otsl_to_html()`（纯标准库，无依赖）：

```python
from recognize_invoice import otsl_to_html
print(otsl_to_html(otsl_text))
```

```html
<table>
  <tr>
    <td rowspan="2">购买方信息</td>
    <td colspan="3">名称：限公司</td>
    <td rowspan="2">销售方信息</td>
    <td colspan="4">名称：重庆限公司</td>
  </tr>
  ...
```

### 6.3 关键信息抽取（KIE）

必须使用官方模板（三个部分缺一不可）：

```text
Extract the "字段1", "字段2". Format the output as a JSON object with keys: "字段1", "字段2". If an item is not in the image, use "###".
```

- 字段名可以是中文，模型能对齐到图上的标签；
- 图上没有的字段返回 `"###"`，**不会**乱编；
- 输出偶尔会带 ```json 代码块包裹，脚本用"截取第一个 `{` 到最后一个 `}`"的方式解析。

实测（发票原图）：

```json
{
  "发票号码": "235020",
  "开票日期": "2023年03月15日",
  "购买方名称": "限公司",
  "购买方纳税人识别号": "91330",
  "销售方名称": "重庆限公司",
  "销售方纳税人识别号": "91500",
  "合计金额": "¥318.58",
  "合计税额": "¥41.42",
  "价税合计(大写)": "叁佰陆拾圆整",
  "价税合计(小写)": "¥360.00",
  "开票人": "王浩"
}
```

> 名称显示为「限公司」、税号只有 5 位，是**原图被打码/模糊**导致，不是模型幻觉。

### 6.4 提示词设计建议

| 想要 | 做法 |
| :--- | :--- |
| 稳定可复现 | 始终 `temperature=0` |
| 只识别局部 | 先把该区域**裁切放大**再送模型，比加文字约束有效得多 |
| 一次出多种结构 | 分多次请求（文本 / 表格 / KIE 各一次），不要试图用一个提示词全要 |
| 减少输出长度 | 只喂裁切后的表格区域，`Table Recognition:` 输出更短更准 |

---

## 7. 脚本手册

所有脚本都接受 `--model` / `--host`，可指向远端 Ollama（如局域网另一台机器）。

### 7.1 `ocr.py` — 通用命令行 OCR

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `image`（位置参数） | 必填 | 图片路径；PDF 请先转图 |
| `-p, --prompt` | `text` | 任务别名 `text`/`table`/`formula`/`seal`/`chart`，也可直接写完整提示词 |
| `--fields` | 空 | KIE 字段，逗号分隔；**给出后优先于 `-p`** |
| `--model` | `openbmb/minicpm-ocr1.0` | 模型名 |
| `--host` | `http://127.0.0.1:11434` | Ollama 地址 |
| `--stream` | 关 | 流式输出（长文档时体验更好） |

```bash
python ocr.py 发票.jpg                              # 文本
python ocr.py 发票.jpg -p table                     # OTSL
python ocr.py 发票.jpg --fields "发票号码,合计金额"    # JSON
python ocr.py 发票.jpg --fields "发票号码" --stream    # 流式
python ocr.py 发票.jpg -p "Extract the \"备注\"..."   # 直接写提示词
```

行为细节：`temperature=0` 固定；HTTP 失败时把响应体一起打印出来（便于定位模型名/路径错误）；
返回码 `0` 成功、`1` 失败，可直接用于 shell 判断。

### 7.2 `recognize_invoice.py` — 发票一键识别

一次请求三件事，输出一份 Markdown（默认 `发票_识别结果.md`）：

1. **KIE**（`INVOICE_FIELDS`，可直接改列表）
2. **整页文本**
3. **表格**：OTSL 原文 + 转换后的 HTML

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `image` | `图片_20261031030910_20_1.jpg` | 发票图片 |
| `--model` / `--host` | 同上 | |
| `--out` | `发票_识别结果.md` | 输出文件 |

```bash
python recognize_invoice.py
python recognize_invoice.py 其他发票.jpg --out result/发票A.md
```

要改字段就编辑文件顶部的 `INVOICE_FIELDS` 列表（字段名会原样进入提示词和 JSON key）。
单次运行约 **25–35 s**（3 次推理，热态）。

### 7.3 `orientation.py` — 方向自动纠正（重要）

模型**不具备方向对齐能力**（见第 10 节），识别前必须先转正：

```bash
python orientation.py 图片.jpg                 # -> 图片_upright.jpg
python orientation.py 图片.jpg --out fixed.jpg
python orientation.py 图片.jpg --no-model      # 不调模型，纯启发式（0/180 歧义时取 0°）
python orientation.py 图片.jpg --fields 发票号码,金额
```

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `image` | 必填 | 输入图 |
| `--fields` | 发票 11 个字段 | 用于"正反打分"的字段 |
| `--no-model` | 关 | 跳过模型，只看 EXIF + 形态学 |
| `--out` | `<原名>_upright.jpg` | 输出路径 |

三步策略：

1. **EXIF**：`ImageOps.exif_transpose()`，手机直出图多半在这一步就解决了；
2. **形态学判向**：把图缩到 800×800 求墨量投影，比较行/列投影的**高频能量比**
   `HF_row/HF_col`——文本横排时相邻行交替强，比值 >1；整幅被转 90°/270° 时 <1。
   实测本张发票：正向 `1.24`，倾倒 `0.80`，阈值取 `1.0`；
3. **正反打分**：候选缩到两个（`{0°,180°}` 或 `{90°,270°}`），各跑一次 KIE，
   用"字段取值是否符合形态"判正反（名称不能是 `*工业仪表*电流变送器`、识别号必须是字母数字、
   大写金额必须以「整/正」结尾……）。规则见 `plausible()`，可按业务扩展。

实测日志（4 个方向全部判对）：

```text
原图   : HF=1.243 horizontal，{0°: 0.818, 180°: 0.636} -> 旋转 0°
rot090 : HF=0.802 vertical  ，{90°: 0.636, 270°: 0.818} -> 旋转 270°
rot180 : HF=1.245 horizontal，{0°: 0.636, 180°: 0.818} -> 旋转 180°
rot270 : HF=0.804 vertical  ，{90°: 0.818, 270°: 0.636} -> 旋转 90°
```

纠正后与原始图**平均灰度差 ≤ 0.15**，即像素级还原。

作为函数调用：

```python
from pathlib import Path
from orientation import detect_upright
upright, info = detect_upright(Path("拍照发票.jpg"))
upright.save("fixed.jpg", quality=95)
print(info["rotate"], info["method"], info.get("kie_scores"))
```

### 7.4 `test_rotation.py` — 旋转鲁棒性实验

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `image` | 默认发票图 | 原始图 |
| `--rotations` | `0,90,180,270` | 要测的角度 |
| `--fields` | 发票 11 个字段 | KIE 字段 |
| `--auto` | 关 | 只做方向检测（内部调用 `orientation.detect_upright`） |
| `--out` | `rotation_test/report.md` | 报告路径 |

```bash
python test_rotation.py                 # 四方向完整对比（约 100 s）
python test_rotation.py --auto          # 只判方向
python test_rotation.py 其他图.jpg --rotations 0,180,90
```

输出四个指标，含义不同，别混淆：

| 指标 | 含义 |
| :--- | :--- |
| 有效字符 | 去掉标点/空白后的字符数，衡量"认出了多少" |
| 与 0° 文本相似度 | `difflib` 序列相似度，衡量"内容对不对" |
| 字段命中 | 非空且非 `"###"` 的字段数，**只表示填了，不表示对** |
| 字段与 0° 一致 | 与标准答案逐字段相等，**这个才是准确率** |

### 7.5 `make_test_page.py` — 生成测试样张

```bash
python make_test_page.py      # -> test_page.png (1000×760)
```

含标题、中英混排正文、跨列表格、行内公式、发票号/金额，用来一次性验证
文本、表格、公式、KIE 四条链路是否都正常。依赖系统字体
`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`（`fonts-noto-cjk` 包）。

### 7.6 `upgrade_ollama.sh` — 升级 Ollama

```bash
sudo bash upgrade_ollama.sh
```

要求目标版本已解压到 `/tmp/ollama-new`（脚本内含校验，缺失时会尝试从
`/tmp/ollama-linux-amd64.tar.zst` 解压）。备份目录为 `/tmp/ollama-backup-<时间戳>`。
细节见 4.3。

---

## 8. 直接调用 API

### 8.1 最小 Python 调用

```python
import base64
import requests

img = base64.b64encode(open("test_page.png", "rb").read()).decode()
r = requests.post("http://127.0.0.1:11434/api/generate", json={
    "model": "openbmb/minicpm-ocr1.0",
    "prompt": "Text Recognition:",
    "images": [img],
    "options": {"temperature": 0},
    "stream": False,
})
print(r.json()["response"])
```

### 8.2 curl

```bash
B64=$(base64 -w0 test_page.png)
curl -s http://127.0.0.1:11434/api/generate -d "{
  \"model\": \"openbmb/minicpm-ocr1.0\",
  \"prompt\": \"Table Recognition:\",
  \"images\": [\"$B64\"],
  \"stream\": false,
  \"options\": {\"temperature\": 0}
}" | python -c "import json,sys; print(json.load(sys.stdin)['response'])"
```

### 8.3 流式

```python
with requests.post(url, json={**payload, "stream": True}, stream=True) as resp:
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line)
            print(chunk.get("response", ""), end="", flush=True)
            if chunk.get("done"):
                break
```

### 8.4 常用请求字段

| 字段 | 用途 |
| :--- | :--- |
| `model` | 模型名，默认 `openbmb/minicpm-ocr1.0` |
| `prompt` | **必须**以官方任务前缀开头 |
| `images` | base64 列表（可多图，但 OCR 建议一次一张） |
| `options.temperature` | 固定 `0` |
| `options.num_ctx` | 默认 16384；长表格/多页拼接时可调到 32768（占更多显存） |
| `keep_alive` | 如 `"30m"`，常驻显存避免每次重载（默认 5 分钟） |
| `stream` | 流式开关 |

> 常驻模型：`curl http://127.0.0.1:11434/api/generate -d '{"model":"openbmb/minicpm-ocr1.0","keep_alive":"30m"}'`
> 会让它预热并保活 30 分钟，批量处理时能省掉每次 ~8 s 的加载时间。

### 8.5 批量处理（多次请求、复用连接）

```python
import base64
from pathlib import Path
import requests

session = requests.Session()
MODEL, HOST = "openbmb/minicpm-ocr1.0", "http://127.0.0.1:11434"

def ocr(path: Path, prompt: str = "Text Recognition:") -> str:
    img = base64.b64encode(path.read_bytes()).decode()
    r = session.post(f"{HOST}/api/generate", json={
        "model": MODEL, "prompt": prompt, "images": [img],
        "options": {"temperature": 0}, "keep_alive": "30m", "stream": False,
    }, timeout=600)
    r.raise_for_status()
    return r.json()["response"]

for p in sorted(Path("inbox").glob("*.jpg")):
    Path("out", p.stem + ".txt").write_text(ocr(p), encoding="utf-8")
```

**不要并发**：4 GB 显存只放得下一份模型，并发请求会排队甚至 OOM，串行反而更快。

---

## 9. 性能实测

硬件：GTX 1050 Ti 4 GB / 4 核 CPU / 11 GiB 内存，模型 `Q4_K_M`，`num_ctx=16384`。

| 场景 | 图片尺寸 | 状态 | 耗时 |
| :--- | :--- | :--- | :--- |
| `ocr.py test_page.png` | 1000×760 | **冷启动**（含加载模型） | **10.97 s** |
| `ocr.py test_page.png` | 1000×760 | 热态 | **3.07 s** |
| `ocr.py 发票.jpg` | 1704×1279 | 热态 | **13.24 s** |
| KIE（11 字段） | 1704×1279 | 热态 | ~12.3 s |
| 文本 + KIE（两次调用） | 1704×1279 | 热态 | ~25.3 s |
| `test_rotation.py` 全流程（8 次调用） | — | 热态 | ~100 s |

显存（推理中 `ollama ps`）：

```text
NAME                             ID              SIZE      PROCESSOR    CONTEXT
openbmb/minicpm-ocr1.0:latest    2aa58eafbdeb    875 MB    100% GPU     16384
```

结论与建议：

- **4 GB 显存足够**，只占 875 MB，还能再放一个小的文本模型（本机另有 llama3.2:1b 等）。
- **耗时主要由输出 token 数决定**，不是图片大小：1000×760 三行文字 3 s，整张发票 13 s。
- 冷启动 ~11 s 是加载模型（一次性），批量处理请用 `keep_alive` 预热（8.4）。
- 想更快：① 只送需要识别的**裁切区域**；② 减少一次请求里要输出内容（分任务请求）；
  ③ 图片长边降到 1600 左右（再低小字会丢）；④ 串行、不要并发。

---

## 10. 质量边界与陷阱

### 10.1 方向：模型没有对齐能力（必看）

同一张发票旋转后识别，结果见 `rotation_test/report.md`：

| 旋转 | 有效字符 | 与 0° 相似度 | 字段与 0° 一致 | 典型错误 |
| :--: | :------: | :----------: | :-----------: | :--- |
| 0° | 229 | 1.000 | 11/11 | — |
| 90° | 217 | 0.901 | 6/11 | 销售方名称→「统一社会信」；合计税额 ¥41.42→¥18.41；大写→「壹拾陆拾圆整」 |
| 180° | 211 | 0.509 | 6/11 | 阅读顺序颠倒；购买方名称→「工业仪表*电流变送器」；税号→「LW6041-9A」 |
| 270° | 200 | 0.858 | 6/11 | 与 90° 类似，表格正文对、抬头与汇总错 |

**关键现象**：字符层面它还认得（90°/270° 的表格行文字几乎全对），但**版面关系崩了**——
谁是谁的字段、阅读顺序全乱。所以：

- KIE 结果在有旋转时**看起来完全正常**（11 个字段全填满），但 5 个是错的；
- 更危险的是下游不会报错。**必须先 `orientation.py` 转正**。

另外：直接问模型「这张图是否上下颠倒」**不可靠**——0° 与 180° 的图都回答 `Yes`。

### 10.2 图像质量

| 现象 | 影响 | 对策 |
| :--- | :--- | :--- |
| 翻拍屏幕（摩尔纹、反光） | 细小字符错（本机发票把 `235020` 认对，但税号只认出 5 位） | 尽量用扫描件/PDF；或裁切 + 提升对比度 |
| 打码 / 黑块 | 该区域输出不完整 | 模型**不会**编造，缺失就缺失，属正确行为 |
| 小字（<10 px） | 漏识别或数字串错 | 裁切该区域放大到 2–3 倍再识别 |
| 长表格跨页 | 每页各出一份 OTSL | 自行按表头拼接 |

### 10.3 表格 OTSL 的常见问题

- 空单元格用 `<ecel>` 占位，**不要**自己压缩列，否则合并关系会错位；
- 个别情况下会漏 `<lcel>`（少一格合并），转 HTML 时表现为列数不齐 —— 建议加一步列数校验；
- 表头缺失时模型会自己"补"一行表头语义，业务侧需按首次出现的行判断。

### 10.4 KIE 的边界

- 字段值为 `"###"` = 图上没有，**不要**当空字符串处理；
- 输出可能被 ```json 包裹，解析要容错（本目录脚本用首尾花括号截取）；
- 字段名越贴近图上原始文字，命中率越高（写「价税合计(小写)」比「总金额」好）。

---

## 11. PDF / 长文档流水线

模型只吃图片。PDF 先按页转图（150–200 DPI 足够，太大会变慢且无收益）：

```bash
pdftoppm -r 200 -png doc.pdf page      # -> page-1.png, page-2.png ...
```

```python
import subprocess, base64
from pathlib import Path
import requests

def pdf_to_pages(pdf: str, dpi: int = 200) -> list[Path]:
    out = Path("pages"); out.mkdir(exist_ok=True)
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, str(out / "page")], check=True)
    return sorted(out.glob("page-*.png"))

def ocr_page(p: Path, prompt: str = "Text Recognition:") -> str:
    img = base64.b64encode(p.read_bytes()).decode()
    r = requests.post("http://127.0.0.1:11434/api/generate", json={
        "model": "openbmb/minicpm-ocr1.0", "prompt": prompt, "images": [img],
        "options": {"temperature": 0}, "keep_alive": "30m", "stream": False,
    }, timeout=600)
    r.raise_for_status()
    return r.json()["response"]

pages = pdf_to_pages("doc.pdf")
md = "\n\n".join(f"## 第 {i+1} 页\n\n{ocr_page(p)}" for i, p in enumerate(pages))
Path("doc.md").write_text(md, encoding="utf-8")
```

用 PyMuPDF 也行（不依赖 poppler）：

```python
import fitz
doc = fitz.open("doc.pdf")
for i, page in enumerate(doc):
    page.get_pixmap(dpi=200).save(f"page-{i+1}.png")
```

更高精度建议：先用版面检测（PaddleOCR-VL layout / MinerU 之类）切出
标题/正文/表格/公式区域，再对每块用对应提示词（`Table Recognition:` 只喂表格），
比整页一次性 `Text Recognition:` 明显更准，也更省时间。

---

## 12. 故障排查

| 症状 | 原因 | 处理 |
| :--- | :--- | :--- |
| `unknown projector type: minicpm_ocr_1_0` | Ollama 版本太旧（<0.40） | 按 4.3 升级；`grep -a minicpm_ocr /usr/local/lib/ollama/libmtmd.so` 确认 |
| `redirect target not allowed ... 198.18.x.x` | Clash TUN/Fake-IP 让 DNS 返回内网地址 | 关代理后 `ollama pull`；或改用 hf-mirror + `ollama create` |
| 拉取卡住/超时 | Go 1.24 TLS 握手到 Cloudflare 抖动（本机 IPv6 不可用） | 直接重试；或配置 `HTTPS_PROXY`，或走镜像 |
| 返回**空字符串** | 提示词前缀不对 / KIE 模板不完整 | 必须 `Text Recognition:` / `Table Recognition:` / … 或 6.3 的完整 KIE 模板 |
| `connection refused` | 服务没起 | `sudo systemctl start ollama && systemctl status ollama` |
| `model 'xxx' not found` | 模型名写错或没拉 | `ollama list` 核对；默认名 `openbmb/minicpm-ocr1.0` |
| 首次调用特别慢（>10 s） | 模型加载 | 正常；用 `keep_alive` 预热，或忽略（只发生一次） |
| 显存不足 / 被 kill | 与其它进程争 4 GB | 换 Q4_K_M、`num_ctx` 降到 4096、关掉其它占用 GPU 的程序 |
| 识别结果顺序乱、字段张冠李戴 | **图片被旋转** | `python orientation.py 图.jpg` 转正后再识别（第 10.1 节） |
| 小字/数字识别错 | 分辨率不足或被缩放 | 裁切该区域放大 2–3 倍单独识别 |
| `/tmp` 空间被占满 | 本机 `/tmp` 是 5.6 G tmpfs（内存盘） | 下载/解压放大 `$HOME`，`rm` 掉 `/tmp/ollama-*` |
| 中文乱码 | 终端 locale | `export LANG=zh_CN.UTF-8`；脚本本身按 UTF-8 写文件 |

排查顺序建议：**服务 → 模型 → 提示词 → 图片方向 → 图像质量**。
前四步任一不对，都会表现为"结果很怪"，而不是报错。

---

## 13. 已知限制

1. **无方向对齐**：旋转/翻转必须先纠正（`orientation.py`）。
2. **一次一页**：没有内置分页/版面切分，长文档需自己拆页 + 按块识别。
3. **不支持 PDF 直输**：必须先转图。
4. **4 GB 显存不能并发**：只能串行，吞吐约 4–5 页/分钟（1000×760 级别）。
5. **手写体、艺术字、低质翻拍**效果明显下降，未做系统性评测。
6. **表格结构**偶有合并标记缺失，转 HTML 后需校验列数。
7. 官方宣传的 `Real5-OmniDocBench 93.68` **未在本机复现**（本目录只做了定向功能验证）。
8. `orientation.py` 的形态学阈值 `1.0` 为经验值，纯印章/纯图表等"无正文"图可能失效。

---

## 14. 参考

- Ollama API 文档：<https://github.com/ollama/ollama/blob/main/docs/api.md>
- 模型页（Ollama Library）：<https://ollama.com/openbmb/minicpm-ocr1.0>
- GGUF 权重（国内镜像）：<https://hf-mirror.com/openbmb/MiniCPM-OCR-1.0-gguf>
- OTSL 表格结构说明：出自 OmniDocBench 的表格标注体系
  （`fcel/lcel/ucel/xcel/ecel/nl` 六种标记）

---

## 附录 A：从零复现的最小检查单

```bash
# 1. 环境
ollama --version                  # >= 0.40
systemctl is-active ollama        # active
nvidia-smi                        # 有 GPU、显存 >= 4 GB

# 2. 模型
ollama pull openbmb/minicpm-ocr1.0
ollama list | grep minicpm

# 3. 功能四连测
python make_test_page.py
python ocr.py test_page.png                    # 文本
python ocr.py test_page.png -p table           # 表格
python ocr.py test_page.png -p formula         # 公式
python ocr.py test_page.png --fields "发票号码,金额"   # KIE

# 4. 性能与设备
ollama ps                                      # 100% GPU
/usr/bin/time -f '%es' python ocr.py test_page.png

# 5. 方向兜底
python test_rotation.py                        # 期望：0° 11/11，其余明显下降
python orientation.py 图片.jpg                  # 期望：判定 0°，输出 _upright.jpg
```

## 附录 B：本目录脚本速查表

| 脚本 | 一行说明 | 典型耗时 |
| :--- | :--- | :--- |
| `ocr.py` | 单图单任务调用 | 3–13 s |
| `recognize_invoice.py` | 发票：KIE + 全文 + OTSL→HTML | 25–35 s |
| `orientation.py` | 方向纠正（EXIF + 形态学 + KIE 打分） | 0.2 s（`--no-model`）/ ~25 s |
| `test_rotation.py` | 四方向鲁棒性实验 | ~100 s |
| `make_test_page.py` | 生成测试样张 | <1 s |
| `upgrade_ollama.sh` | 升级 Ollama 并重启服务 | ~10 s |

---

*本手册内容基于本机（Ubuntu 26.04 / GTX 1050 Ti 4 GB / Ollama 0.40.13）实测整理。*
