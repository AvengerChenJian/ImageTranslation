# 商品图翻译

上传一张商品图片，自动识别图中文字 → 翻译成目标语言 → 擦除原文 → 按原位置、原字号、原配色重绘译文，输出一张新图。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
python -m uvicorn backend.main:app --port 8000
```

打开 http://127.0.0.1:8000 ，上传图片、选择源/目标语言、点「开始转换」。

`.env` 已配置有道翻译（默认 `TRANSLATOR=youdao`）：

```env
TRANSLATOR=youdao
YOUDAO_APP_KEY=你的应用ID
YOUDAO_APP_SECRET=你的应用密钥
```

> 注意：Google 翻译（`translate.googleapis.com`）在国内网络不可达，
> 且 `translate.google.cn` 的免费接口已废弃返回 404，因此默认使用有道。

> 首次运行会自动下载 RapidOCR 的模型文件（十几 MB），需联网一次。

## 处理流程

```
上传图片 + 语言规则
   │
   ├─ 1. OCR          RapidOCR / PaddleOCR / Tesseract / 外部 HTTP 服务
   ├─ 2. 行合并       把散落的文本框合并成阅读行
   ├─ 3. 空格修复     按像素间隙补回 OCR 吞掉的词间空格（见下方说明）
   ├─ 4. 样式分析     估算原字号、提取文字色与背景色、判断背景是否纯色
   ├─ 5. 翻译         整批送翻译 API
   ├─ 6. 排版         自动换行 + 二分缩小字号，使译文装进原框
   ├─ 7. 擦除         纯色背景→主色填充；复杂背景→OpenCV 内容感知修复
   └─ 8. 重绘         按原中心点、原颜色（对比度不足时自动黑白）、原角度绘制
```

## 目录结构

```
backend/
  main.py            FastAPI 入口与接口
  config.py          配置（读 .env）
  pipeline.py        主流程串联
  languages.py       语言代码与字体/翻译服务的映射
  ocr/               识别引擎（适配器）
    base.py          TextBox / TextLine 数据结构 + 行合并
    rapid_ocr.py     默认：RapidOCR
    paddle_ocr.py    可选：PaddleOCR / EasyOCR
    external_ocr.py  外部程序：Tesseract（命令行）、任意 HTTP OCR 服务
  translate/         翻译引擎（适配器）
    google.py        默认：deep-translator 免费后端
    youdao.py        有道翻译
    deepl.py         DeepL
    mock.py          离线调试（原样返回）
  image/
    analyze.py       前景色/背景色/背景复杂度
    inpaint.py       擦除
    render.py        字体选择、自动排版、绘制
frontend/            单页页面，无需 npm 构建
results/             生成的图片
```

## 换用别的开源识别程序

识别是可插拔的，改 `.env` 里的 `OCR_ENGINE` 即可，业务代码无需改动：

| 值 | 说明 | 额外要求 |
|---|---|---|
| `rapid`（默认） | RapidOCR，ONNX 版 PaddleOCR 模型，CPU 友好 | `pip install rapidocr-onnxruntime` |
| `paddle` | PaddleOCR 原版 | `pip install paddleocr paddlepaddle` |
| `easy` | EasyOCR | `pip install easyocr`（依赖 torch） |
| `tesseract` | 系统安装的 Tesseract 可执行文件 | 设置 `TESSERACT_CMD`、中文需 `TESSERACT_LANG=chi_sim` |
| `http` | 外部 OCR 服务（Umi-OCR、自建服务、Docker 容器） | 设置 `OCR_HTTP_URL` |

`http` 模式会自动兼容常见的返回格式（四点多边形或 `x1,y1,x2,y2` 矩形），例如：

```json
{"data": [{"box": [10, 20, 200, 60], "text": "Hello", "score": 0.98}]}
{"result": [[[[10,20],[200,20],[200,60],[10,60]], "Hello", 0.98]]}
{"boxes": [...], "texts": [...], "scores": [...]}
```

自定义字段用 `OCR_HTTP_EXTRA`（JSON 字符串）追加，例如对接 Umi-OCR：

```env
OCR_ENGINE=http
OCR_HTTP_URL=http://127.0.0.1:1224/api/ocr
OCR_HTTP_EXTRA={"options":{"data.format":"dict"}}
```

新增引擎只需继承 `backend/ocr/base.py` 的 `BaseOCR` 并在 `backend/ocr/__init__.py` 注册。

## 不翻译的内容（商标 / 品牌名）

两种方式，命中后该行**不翻译、不擦除、不重绘**，原像素原样保留：

1. **手动勾选**：上传图片后自动识别并列出所有文本行，取消勾选即保留原文；
   顶部可一键「全部 / 全部不翻译」。
2. **保护词**：在识别结果里点「保护」把某个词加入名单，之后所有包含该词的
   行都会自动跳过，适合反复出现的品牌名。词表存在项目根目录
   `protected_terms.json`，可直接手工编辑，或用接口增删。

识别结果会缓存在服务端（`"ocr_id"`），转换时可复用，不会重复跑 OCR。

## 空格修复

识别模型有时会把整行连成不带空格的串（`PREMIUM ARABICA` → `PREMIUMARABICA`），
翻译 API 遇到这种串通常原样返回。`backend/image/textfix.py` 会做竖列投影，
用词间隙 / 字间隙的宽度差异把空格插回原位：

```
PREMIUMARABICA  内部空隙宽度: 6 5 7 8 8 8 [17] 4 1 4 8 6 3
                                            ^ 词间距约为字间距的 2 倍以上
```

判定规则自适应：保留宽度 ≥ `max(0.30×字高, 0.62×最大空隙)` 的空隙，
且要求最大空隙相对次大空隙有明显跳变，切出的每段不少于 2 个字符——
任一条不满足就放弃修复（宁可不补，也不乱切）。

## 换用别的翻译服务

`TRANSLATOR`：

| 值 | 说明 | 需要的配置 |
|---|---|---|
| `google`（默认） | deep-translator 免费后端 | 无 |
| `youdao` | 有道翻译 | `YOUDAO_APP_KEY`、`YOUDAO_APP_SECRET` |
| `deepl` | DeepL | `DEEPL_AUTH_KEY`（免费版 `DEEPL_FREE=true`） |
| `mock` | 原样返回，离线联调 | 无 |

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/translate` | `file`, `src_lang`, `tgt_lang`, `outline`, `ocr_id`, `skip`（行下标 JSON）→ 结果图 URL + 文本行 |
| POST | `/api/ocr` | 识别并返回可勾选的行 + `ocr_id` + 带框可视化图 |
| GET | `/api/terms` | 保护词列表 |
| POST | `/api/terms/add` | 添加保护词（`term`） |
| POST | `/api/terms/remove` | 移除保护词（`term`） |
| GET | `/api/languages` | 语言列表 |
| GET | `/api/status` | 当前 OCR / 翻译引擎 |

## 可调参数（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `OCR_MIN_SCORE` | 0.5 | 置信度过滤阈值 |
| `OCR_MAX_SIDE` | 1600 | OCR 前缩放的最大边长（坐标会映射回原图） |
| `WIDTH_EXPAND` | 1.20 | 译文宽度最多放到原框的几倍 |
| `HEIGHT_EXPAND` | 1.80 | 译文高度最多放到原框的几倍（超出会自动折行/缩小字号） |
| `MIN_FONT_SIZE` | 10 | 最小字号 |

## 已知限制

- **竖排文字**和**透视变形**文字暂不支持（只支持平面旋转）。
- 艺术字、带描边/阴影的文字擦除后可能留残影，可调 `inpaint.py` 里的膨胀系数。
- 译文明显长于原文时会自动缩小字号，极端情况下仍可能轻微溢出原框。
- 结果图目前不自动清理，可定期删除 `results/`。
