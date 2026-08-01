# Toolbox 项目架构书（v4.0）

> 适用范围：本架构书描述截至 **v4.0** 的 `toolbox` 桌面工具箱整体结构、分层职责、运行时数据流与编码规约。
> 配套文档：[新增 Tool 开发指南（v4.0）](./新增Tool开发指南.md)
> 历史整改/阶段报告与早期原型已移至 `docs/archive/`（仅供追溯，不参与当前架构）。

---

## 0. 概览

`toolbox` 是一个基于 **PySide6** 的本地桌面工具箱，采用**分层 + 端口与适配器（Ports & Adapters / 六边形架构）**风格组织。
核心理念：**业务核心（`core`）零 Qt 依赖、可被独立测试；所有 GUI 与第三方库都被限制在边界（UI 层 / `adapters`）之内。**

v4.0 内置 4 个工具（Tool）：

| 工具名（`get_name`） | 导航标题（`get_nav_title`） | 能力 |
| --- | --- | --- |
| `Quiz2Slide` | 📑 题库转PPT | Word 题目文档 → 可编辑 PowerPoint |
| `SimilarityChecker` | 🔍 试题查重 | 主文档 vs 多副文档 / 多文档两两查重，导出报告 |
| `JsonExam` | 📝 试卷生成 | JSON 题目数据 → Word 题本 + 解析文档 |
| `Pdf2Slide` | 📄 PDF转PPT | PDF 逐页 → 保留可编辑文字的 PowerPoint |

技术栈：Python 3.13 / PySide6 / python-docx / python-pptx / PyMuPDF / Pydantic（契约层）。

---

## 1. 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                              UI 层 (PySide6)                            │
│                                                                        │
│  app.py ── 装配 + 主窗口 (ToolboxApp)                                  │
│     │                                                                  │
│     ├── views/  BaseView + 4 个 View（仅渲染/事件绑定）                │
│     │       └── 订阅 ViewModel 的 Signal                              │
│     ├── viewmodels/  4 个 ViewModel（胶水：命令转发 + 事件→信号）      │
│     ├── theme.py / theme.qss / widgets.py  （主题 & 可复用控件）       │
│     └── infra/    QtTaskRunner · QtEventEmitter · preview_escape       │
└───────────────┬───────────────────────────┬──────────────────────────┘
                │ 命令(Request)              │ 事件(DomainEvent)
                ▼                            ▲
┌──────────────────────────────────────────────────────────────────────┐
│                    core 业务核心（零 Qt 依赖，可单测）                   │
│                                                                        │
│  services/  5 个 ServiceImpl（业务编排，emit 事件）                     │
│     │  依赖                              ┌── ports/ (Protocol 端口)    │
│     ▼                                    │   services.py / io.py      │
│  adapters/  4 个适配器（封装 python-docx / pptx / pymupdf）             │
│                                        │   tasks.py / events.py       │
│  models/   Question · ExamQuestion     └── DI 容器 (core/di.py)        │
└──────────────────────────────────────────────────────────────────────┘
                ▲
                │ 共享契约
┌──────────────────────────────────────────────────────────────────────┐
│  shared/  contracts.py（Pydantic Request/Result/Event）· errors.py     │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.1 分层职责

| 层 | 目录 | 职责 | 允许依赖 |
| --- | --- | --- | --- |
| 契约 | `shared/` | 前后端通信的 Pydantic 模型、异常体系 | 仅标准库 / pydantic |
| 业务核心 | `core/` | 业务规则、编排、端口定义 | `shared`、`core` 内部 |
| UI 层 | `ui/` + `app.py` + `theme.py` + `widgets.py` | 渲染、事件绑定、后台线程调度 | 以上全部 + PySide6 |
| 入口 | `app.py` | 依赖装配、主窗口、工具注册 | 以上全部 |

### 1.2 关键设计原则

1. **`core` 零 Qt 依赖**：`core/` 与 `shared/` 绝不 `import PySide6`。GUI 线程、信号、调色板全部在 `ui/` 解决。
2. **端口与适配器（有意为之，不是基类）**：第三方库（docx/pptx/pymupdf）只出现在 `core/adapters/`。Service 依赖的是 `core/ports/` 中的 **`@runtime_checkable Protocol`**，而非具体类，便于 mock 测试。
3. **依赖注入**：`core/di.py` 的 `Container.build()` 负责把 `adapters → services` 串起来，并以字符串 key 注册。`app.py` 在启动时 `Container.build(...)` 并 `resolve(...)`。
4. **单一事件通道**：所有后台进度/完成/失败都封装成 `DomainEvent`，经由**唯一的** `QtEventEmitter` 实例推送；ViewModel 订阅该 emitter，按 `EventType` 过滤后转成 Qt `Signal`。
5. **单一任务运行器**：所有耗时操作经 `@async_task` 装饰器提交给 `QtTaskRunner`（`QThread` 封装），不在 UI 线程执行。

---

## 2. 目录结构

```
toolbox/
├── app.py                 # 入口：装配 + 主窗口 + 工具注册
├── theme.py / theme.qss   # 主题（颜色/令牌/QSS 片段）
├── widgets.py             # 可复用控件（按钮/进度条/拖放区/Toast/...）
├── shared/
│   ├── contracts.py       # Pydantic 契约：Request/Result/Event/EventType
│   └── errors.py          # ToolboxError 异常体系
├── core/
│   ├── ports/             # Protocol 端口：services/io/tasks/events
│   ├── models/            # Question · ExamQuestion（领域模型）
│   ├── adapters/          # 第三方库封装（docx/pptx/pymupdf）
│   ├── services/          # 业务服务实现（编排 + emit 事件）
│   └── di.py              # 依赖注入容器
├── ui/
│   ├── views/             # BaseView + 4 个 View
│   ├── viewmodels/        # 4 个 ViewModel（胶水层）
│   └── infra/             # QtTaskRunner · QtEventEmitter · preview_escape
├── tests/                 # pytest 用例（含对 core 的纯单元测试）
├── docs/                  # 本文档与开发指南（v4.0）
└── assets/                # 图标/logo
```

---

## 3. 核心分层详解

### 3.1 `shared/` —— 契约与异常

**`shared/contracts.py`**（约 310 行）
- 所有 Request / Result 均为 **Pydantic `BaseModel`**（带类型与文档字符串）；前后端禁止直接传裸 `dict`。
- `EventType(str, Enum)`：后端→前端事件类型。当前成员：
  `CHECK_*`(STARTED/PROGRESS/COMPLETED/FAILED)、`EXTRACT_*`(COMPLETED/FAILED)、
  `PPTX_*`(PROGRESS/COMPLETED/FAILED)、`EXAM_*`(PROGRESS/COMPLETED/FAILED)、
  `PDF_*`(PROGRESS/COMPLETED/FAILED)。
- **事件模型**：`_BaseEvent(type)` → 各具体事件（`ProgressEvent` / `CheckStartedEvent` / `CheckCompletedEvent` / `ExtractCompletedEvent` / `PptxCompletedEvent` / `ExamCompletedEvent` / `PdfCompletedEvent` / `FailedEvent` / `ExamFailedEvent` / `PdfFailedEvent`）。
  - `ProgressEvent` 被 4 个工具复用（其 `type` 为 `Literal[CHECK_PROGRESS, PPTX_PROGRESS, EXAM_PROGRESS, PDF_PROGRESS]`）。
  - `DomainEvent` 是上述事件的 `Union`（以 `type` 作判别字段），供 `EventEmitter.emit` 统一推送。
- ⚠️ **不对称点**：`CHECK_/EXTRACT_/PPTX_FAILED` 共用 `FailedEvent`；而 `EXAM_FAILED`、`PDF_FAILED` 各自有 `ExamFailedEvent`/`PdfFailedEvent`。新增工具时建议为失败事件单独建类，避免与既有判别冲突。

**`shared/errors.py`**（约 51 行）
- `ToolboxError`（基类）→ 业务异常族，例如 `OutputOverwriteError`、`NoQuestionsExtracted`、`DocumentReadError`、`OutputWriteError` 等。
- 需要 View 按类型分流时，在此新增继承 `ToolboxError` 的异常。

### 3.2 `core/` —— 业务核心（零 Qt）

#### 3.2.1 `core/ports/`（Protocol 端口，非基类）
| 文件 | Protocol | 关键方法签名 |
| --- | --- | --- |
| `services.py` | `SimilarityService` / `ExtractionService` / `PptxService` / `PdfSlideService` / `ExamGeneratorService` | `check(request)` / `extract(request)` / `generate(request)` / `convert(request)` |
| `io.py` | `DocumentLoader` / `PptxWriter` / `PdfSlideConverter` / `ExamDocxWriter` | `load_paragraphs(path)` / `build(...)` / `convert(request, on_progress)` |
| `tasks.py` | `TaskHandle`(`cancel`/`is_running`) · `TaskRunner`(`submit(...)`) | 调度抽象 |
| `events.py` | `EventEmitter`(`emit`/`on_event`) | 事件通道抽象 |

> 均为 `@runtime_checkable Protocol`；适配器**不继承任何基类**，仅靠方法签名结构化匹配（鸭子类型）。

#### 3.2.2 `core/models/`
- `Question`（`question.py`）：题目领域模型（`lines` / `source_file` / `index` 等）。
- `ExamQuestion`（`exam_question.py`）：试卷题目（含 `images` 等），供 JSON→Word 流程。

#### 3.2.3 `core/adapters/`（4 个，封装第三方库）
| 适配器 | 文件 | 实现的端口 | 第三方库 |
| --- | --- | --- | --- |
| `DocxLoaderAdapter` | `docx_loader.py` | `DocumentLoader` | python-docx |
| `PptxWriterAdapter` | `pptx_writer.py` | `PptxWriter` | python-pptx |
| `DocxExamWriterAdapter` | `docx_exam_writer.py` | `ExamDocxWriter` | python-docx |
| `PdfSlideConverterAdapter` | `pdf_slide_converter.py` | `PdfSlideConverter` | PyMuPDF + python-pptx |

#### 3.2.4 `core/services/`（5 个服务实现）
| 服务 | 文件 | 端口 | 关键行为 |
| --- | --- | --- | --- |
| `ExtractionServiceImpl` | `slide_builder.py` | `ExtractionService` | `loader.load_paragraphs → parse_questions → emit(ExtractCompletedEvent)` |
| `PptxServiceImpl` | `slide_builder.py` | `PptxService` | 校验（输出≠模板）→ 进度事件 → `writer.build` → `PptxCompletedEvent`；`_same_path` 防覆盖 |
| `SimilarityServiceImpl` | `similarity_service.py` | `SimilarityService` | 1对多 / 多对多查重；`score_questions` 打分；失败抛 `NoQuestionsExtracted` |
| `JsonToWordServiceImpl` | `json_to_word_service.py` | `ExamGeneratorService` | 解析→并发预下载图片（有限并发）→生成题本+解析；图片失败不中断，汇总 `failed_images` |
| `PdfSlideServiceImpl` | `pdf_slide_service.py` | `PdfSlideService` | 校验（输出≠模板/源）→ `converter.convert` → `PdfCompletedEvent` |

> ⚠️ `core/services/__init__.py` **导出不完整**：仅导出 `SimilarityServiceImpl / ExtractionServiceImpl / PptxServiceImpl`，漏了 `JsonToWordServiceImpl` 与 `PdfSlideServiceImpl`（它们由 `core/di.py` 直接 import）。新增服务时务必补齐 `__init__.py` 与 `__all__`。

#### 3.2.5 `core/di.py`
`Container.build(*, task_runner, event_emitter) -> Container`：
- 实例化 4 个适配器 → 5 个服务（注入 loader/writer/emitter）。
- 以字符串 key 注册：`extraction` / `pptx` / `similarity` / `exam` / `pdf_slide` / `task_runner` / `event_emitter`。
- API：`register(key, instance)` / `resolve(key)`（裸 `dict` 查表，**无类型安全**）。

### 3.3 `ui/` —— UI 层

#### 3.3.1 `ui/infra/`
- `QtTaskRunner`（`qt_task_runner.py`，约 126 行）：`QThread` 封装；`submit(func, *, args, kwargs, on_progress, on_result, on_error) -> QtTaskHandle`。
  - **`@async_task` 装饰器**：仅挂 `on_error`（回调 `ViewModel.on_async_error`）；结果与进度全部走事件通道。
  - `QtTaskHandle.cancel()` = `worker.quit() + wait()`（阻塞）。
- `QtEventEmitter`（`qt_event_emitter.py`，约 30 行）：结构实现 `EventEmitter` 端口（`emit` / `on_event`），跨线程时 Qt 自动 `QueuedConnection` 排到 UI 线程。
- `preview_escape`（`preview_escape.py`，约 35 行，零 Qt）：
  - `escape_preview_line(text)`：`html.escape` 后，用白名单正则把 `<b>/<i>/<u>/<br>`（含闭合/`/` 形式）还原。
  - `sanitize_font_name(name)`：剔除 `{ } " ' \` ;` 等可脱离 CSS 的字符后转义。
  - **白名单仅 4 个标签**，且不允许任何属性；其余标签与所有属性永久转义（防 XSS/样式注入）。

#### 3.3.2 `ui/viewmodels/`（胶水层，无基类）
- 4 个 ViewModel 各自直接继承 `QObject`，**没有统一的基类**（靠复制粘贴保持一致的模板）。详见[开发指南](./新增Tool开发指南.md)。
- 每个 VM 持有 service + `task_runner` + `event_emitter`，定义业务 `Signal`，并实现 `on_async_error` / `cancel_current` / `_on_event` 与 `@async_task` 命令方法。
- ⚠️ **信号载荷不一致**：`JsonExamViewModel.failed` 是 `Signal(object)`（发异常本体，供 `isinstance` 分流），其余 3 个发 `str(exc)`。
- ⚠️ **共享 emitter 陷阱**：4 个 VM 共用同一个 `QtEventEmitter` 实例，全部 `_on_event` 都会收到所有事件，靠 `EventType` 过滤。**新增工具必须新增专属 `EventType`**，否则会串台（`SlideViewModel` 已把 `CHECK_FAILED` 也映射到 `pptx_failed`，属历史耦合）。

#### 3.3.3 `ui/views/`
- `BaseView(QWidget)`（`base_view.py`，约 38 行）：定义 `get_name()` / `get_nav_title()` / `get_description()`（后两者有默认），可选重写 `on_activate()`。`get_name`/`get_description` 为抽象（抛 `NotImplementedError`）。
- 4 个 View 遵循统一的构造与样式模式（见 §6）。

#### 3.3.4 `theme.py` / `theme.qss` / `widgets.py`
见 §7 主题系统。

---

## 4. 数据流与运行时

### 4.1 一次命令的完整链路（以「题库转PPT」为例）

```
用户点击「开始转换」
  → SlideView.on_convert()                      [UI 线程]
  → SlideViewModel.extract(request)             [@async_task 装饰]
  → QtTaskRunner.submit(_run)  → QThread 后台    [后台线程]
  → ExtractionServiceImpl.extract()
       └─ loader.load_paragraphs + parse_questions
       └─ emitter.emit(ExtractCompletedEvent)     [跨线程 → 排到 UI 线程]
  → SlideViewModel._on_event → self.extracted.emit(result)
  → SlideView._on_extracted() → 预览确认弹窗
  → 用户确认 → SlideViewModel.generate(request)
  → PptxServiceImpl.generate() → 进度事件序列 → PptxCompletedEvent
  → SlideView._on_pptx_completed() → 写入文件 + Toast
```

要点：
- 业务结果/进度 **只经事件通道返回**，`@async_task` 不挂 `on_result`。
- 后台异常由 `QtTaskRunner` 调 `ViewModel.on_async_error` → 转成 `failed` 信号。
- 线程清理：`ToolboxApp.closeEvent` 遍历 `_tools`，对每个可调用 `stop_worker` 的视图调之 → `vm.cancel_current()` → `handle.cancel()`。

### 4.2 主题热切换
- 检测源：`QApplication.styleHints().colorScheme()` 与 `Qt.ColorScheme.Dark` 比较（**不读 QSettings/环境变量，无手动开关**）。
- **集中刷新（v4.0，Phase 4）**：`app.py` 保留唯一一处 `connect(styleHints().colorSchemeChanged, ...)`，回调里 `theme.refresh()`；`Theme` 为全局单例，`refresh()` 末尾通过 `theme_changed` 信号广播，各 View 订阅 `theme.theme_changed` 后只做 `_restyle_all()`（**不再各自连 OS 信号、不再在处理器内调 `refresh()`**，否则自触发死循环）。OS 级连接由 5 处降为 1 处。

### 4.3 工具注册
`app.py`：`Container.build` → 造 4 个 VM → `_register_tools(...)` → 逐个 `_add_tool(View)`。
`_add_tool` 用 `get_nav_title()` 作导航项文本、`f"{get_name()}\n{get_description()}"` 作 tooltip。
`_on_nav_changed` 切换时调 `tool.on_activate()`（当前 4 个 View 均未重写，为空实现）。

---

## 5. 四大内置工具对照表

| 工具 | Service(impl) | Adapter | ViewModel | View | 关键 Request/Result |
| --- | --- | --- | --- | --- | --- |
| Quiz2Slide | `ExtractionServiceImpl` + `PptxServiceImpl` | `DocxLoaderAdapter` + `PptxWriterAdapter` | `SlideViewModel` | `SlideView` | `ExtractQuestionsRequest`/`Result` · `GeneratePptxRequest`/`Result` |
| SimilarityChecker | `SimilarityServiceImpl` | `DocxLoaderAdapter` | `SimilarityViewModel` | `SimilarityView` | `SimilarityRequest`/`Result`(`OneToMany`/`ManyToMany`) |
| JsonExam | `JsonToWordServiceImpl` | `DocxExamWriterAdapter` | `JsonExamViewModel` | `JsonExamView` | `GenerateExamRequest`/`Result` |
| Pdf2Slide | `PdfSlideServiceImpl` | `PdfSlideConverterAdapter` | `PdfSlideViewModel` | `PdfSlideView` | `ConvertPdfRequest`/`Result` |

---

## 6. 视图通用规范（UI 一致性）

4 个 View 高度同构，新视图应以 `SimilarityView` 为范本（其 `_restyle_all` 最完整）。通用模式：

1. **构造顺序**（`__init__`）：
   `self._vm = view_model` → `self.theme = Theme()` → 业务状态字段 → `self.settings = QSettings("<AppName>", "<AppName>")`（两参同名）→ `_setup_ui()` → `_connect_view_model()` → `_load_settings()` → `colorSchemeChanged.connect(self._on_theme_changed)`。
2. **三列表**：`_setup_ui` 开头初始化 `self._field_labels` / `self._section_labels` / `self._module_cards`，供 `_restyle_all` 统一刷新。
3. **卡片/字段**：复制 `_make_module_card(title)`（含 `setObjectName("module_card")`/`"card_title"`）与 `_make_labeled_field(label_text, widget)`。
4. **根布局**：`QVBoxLayout(self)`，`setContentsMargins(24,20,24,20)`，`setSpacing(0)`；内容包在 `QScrollArea(widgetResizable, H:AlwaysOff, V:AsNeeded)` 中（`self._scroll`）；内容 `spacing=16`。
5. **`_setup_ui` 末尾三连**：`self.toast = ToastNotification(self, theme=self.theme)` → `self._update_xxx_state()` → `self._restyle_all()`。
6. **`_restyle_all()` 必须覆盖**：palette(`window_solid_bg`) → 卡片 `qss_card()` → `_field_labels`(12px/`text_secondary`) → `_section_labels` `qss_section_header()` → 进度条 `qss_progress_bar()` → 所有 `AppButton.set_theme(t)`（**按钮须存成实例属性**；SlideView 的 `change_btn` 已与 SimilarityView 对齐，在 `_restyle_all` 调 `set_theme`）→ 所有 `StepperInput.set_theme(t)` → **DropZone `dz._theme = t; dz._apply_style()`**（SlideView 已对齐 SimilarityView）→ 结尾复制 `_scroll` 滚动条样式块。
7. **`stop_worker()`**：4 个 View 均实现为 `self._vm.cancel_current()`（1 行）。`on_activate()` 均未重写。
8. **QSettings 持久化**：`blockSignals(True)` 包裹 `_load_settings` 的全部赋值，避免半载状态被 `_save_settings` 写回。
9. **门禁方法**：首行 `if self.<btn>._loading: return`，再按输入完备度 `set_actionable(False, "请先选择 XXX")`。
10. **「打开文件夹」富文本链接**：`label.setTextFormat(Qt.RichText)` + `linkActivated.connect(...)` + `<a href="folder:{folder}" style="color:{theme.accent};text-decoration:underline;">打开文件夹</a>`。

> ⚠️ **已知不一致（供重构参考）**：① ~~SlideView 的 `_restyle_all` 漏刷 DropZone 与 `change_btn`~~ ✅ **已修复（v4.0，已对齐 SimilarityView）**；② 同一概念「题号格式」在 SlideView 存 `question_num_fmt`，SimilarityView 存 `num_pattern`；③ `first_line_indent` 在 QSettings 中以**字符串** `"true"/"false"` 存储，读取时 `== "true"` 比较；④ ~~三种「打开文件夹」实现（`subprocess` / `os.system` / 兼容 `folder:` 前缀）不统一~~ ✅ **已修复（v4.0，Phase 2，已抽 `ui/infra/open_folder.py`）**；⑤ 部分设计令牌（`spacing`/`page_pad_*`/`font_*`）在 View 中未被引用，布局仍是硬编码。

---

## 7. 主题系统

**`theme.py`**（`Theme` 类，约 231 行）：
- **颜色**：`_set_colors()` 定义 37 个颜色属性（浅/深两套一一对应），如 `accent`(#1677ff/#3b93ff)、`text_primary`、`window_bg`、`card_bg`、`danger`、`nav_selected_bg` 等。
- **设计令牌** `_set_tokens()`（10 个，跨深浅恒定）：`radius=6`、`spacing=16`、`control_spacing=8`、`page_pad_x=24`、`page_pad_y=20`、`font_family`、`font_page_title=14`、`font_module_title=13`、`font_body=12`、`font_hint=12`。其中 `font_module_title` 被 `theme.qss` 的 `# section_header` 块使用；其余多数令牌在 View 中未实际消费。
- **QSS 片段方法**（4 个，每次调用都重读 `theme.qss` 文件 → 改 QSS 后下次 `_restyle_all` 即生效）：
  - `qss_card()` → `# card` 块；`qss_divider()` / `qss_section_header()` 返回**裸 CSS 属性串**（无选择器，只能给单个控件 `setStyleSheet`，不能当全局样式表）；
  - `qss_progress_bar()` → `# progress_bar` 块（含 `height:6px`）。
- 私有支撑：`_read_qss()`（`OSError` 时回退内置 `_EMBEDDED_QSS`）、`_qss_block(name)`（`string.Template` 替换 `$var`，特判 `radius→"6px"`）。
- **暗色检测**：`refresh()` 读 `QApplication.styleHints().colorScheme()`，不读 QSettings/环境变量，无手动开关。
- **单例 + 集中刷新**：`Theme` 为全局单例（`get_theme()` 等价 `Theme()`），`refresh()` 末尾经 `theme_changed` 信号广播；视图统一订阅该信号做重绘（见 §4.2）。

**`theme.qss`**（17 行）：4 个块（`# card` / `# divider` / `# progress_bar` / `# section_header`），用 `$var`/`${var}` 模板语法（`string.Template`）。

**`widgets.py`**（约 871 行，8 个可复用控件）：`AppButton`（圆角/primary|secondary/禁用原因 tooltip/加载态）、`AnimatedButton`(AppButton+按压高度动画)、`AnimatedProgressBar`(300ms 平滑过渡)、`StepperInput`(−/输入/+)、`ToastNotification`(顶部滑入)、`DropZone`(单文件拖放)、`MultiDropZone`(多文件拖放)、`ErrorDialog`(全局错误弹窗，含 `extraClicked` 信号)。

> ⚠️ **控件坑**：① `AppButton.setEnabled` 被重写为 `set_actionable(enabled, "")`，会清空已设禁用原因；② `StepperInput` 在 `QSpinBox` 模式下 `valueChanged` **永不发射**（须手动把 ± 按钮 `clicked` 接到保存逻辑）；③ `DropZone`/`MultiDropZone` 的 `theme=None` 会 `AttributeError`（theme 事实上必传）；④ `MultiDropZone` 没有 `file_cleared` 信号。

---

## 8. 编码规约与已知技术债

| # | 事项 | 建议 |
| --- | --- | --- |
| 1 | `core/services/__init__.py` 导出不全 | ✅ **已修复（v4.0）**：补齐 `JsonToWordServiceImpl`/`PdfSlideServiceImpl` 导出 |
| 2 | ViewModel 无基类、4 份复制 | ✅ **已修复（v4.0）**：抽 `BaseViewModel`，内置 `_WATCHED` 串台防护，4 个 VM 继承之 |
| 3 | 适配器无基类（Protocol 有意） | 保持；勿强行加基类 |
| 4 | 共享 `QtEventEmitter`，EventType 须专属 | 新增工具务必加 `XXX_PROGRESS/COMPLETED/FAILED`；`contracts.py` 的 `EventType` 已加「专属约定」注释。`SlideViewModel` 原误监听 `CHECK_FAILED`→`pptx_failed` 的历史耦合 ✅ **已解耦（v4.0，Phase 2）**：`SlideViewModel` 不再监听 `CHECK_FAILED`（`CHECK_*` 属 SimilarityChecker） |
| 5 | `failed` 信号载荷不一致（str vs object） | ✅ **已修复（v4.0，Phase 2）**：四个 VM 的失败信号统一为 `Signal(object)`，`on_async_error` 透传异常对象（以 `JsonExamViewModel` 为范本），视图侧统一 `msg = message if isinstance(message, str) else str(message)` 处理 |
| 6 | `Theme` 非单例、≥5 实例 | ✅ **已修复（v4.0，Phase 4）**：`Theme` 改为全局单例（`__new__` 缓存 + `_initialized` 守卫），升级为 `QObject` 暴露 `theme_changed` 信号；`refresh()` 末尾广播该信号，`app.py` 保留唯一 `colorSchemeChanged` 接线触发 `refresh()`，4 个 View 改订阅 `self.theme.theme_changed`（处理器去掉 `refresh()` 防自触发死循环）。OS 级连接由 5 处降为 1 处 |
| 7 | 设计令牌多数未消费，布局硬编码 | ✅ **已修复（v4.0，Phase 4）**：View 布局中等于令牌值的魔数（`24/20/16/8`）值保留替换为 `self.theme.page_pad_x/page_pad_y/spacing/control_spacing`；`font_*`/`radius` 等令牌早已由 `theme.qss` 的 `$var` 注入经 `Theme._qss_block` 消费 |
| 8 | QSettings key 命名不一致 | ✅ **已修复（v4.0，Phase 3）**：抽 `ui/infra/settings_keys.py` 按工具集中常量，保持原字符串值不变（不破坏已有用户持久化），消除拼写/命名不一致隐患 |
| 9 | `first_line_indent` 以字符串存布尔 | ✅ **已修复（v4.0，Phase 3）**：`json_exam_view` 改为真布尔存储；读取兼容旧 `"true"/"false"` 字符串值（`raw if isinstance(raw, bool) else str(raw) == "true"`） |
| 10 | 视图 `_restyle_all` 覆盖不一致 | 以 SimilarityView 为准统一 |
| 11 | 四处「打开文件夹」实现不统一（subprocess / os.system / `folder:` 前缀） | ✅ **已修复（v4.0，Phase 2）**：抽 `ui/infra/open_folder.py` 的 `open_folder()`，四个 View 统一调用，自动剥离 `folder:` 前缀、跨平台派发 |

---

## 9. 如何新增一个 Tool

完整步骤、代码模板与避坑清单见 **[新增 Tool 开发指南（v4.0）](./新增Tool开发指南.md)**。
一句话流程：`shared/contracts.py`（Request/Result/EventType/Event） → `core/ports`（Protocol） → `core/adapters`（封装库） → `core/services`（编排+emit） → `core/di.py`（注册） → `ui/viewmodels`（胶水） → `ui/views`（渲染） → `app.py`（装配+注册）。

---

## 10. 测试

- `tests/` 下为 pytest 用例，覆盖 core 纯逻辑（`parse_questions` / `score_questions` / services / `preview_escape` 等）与部分 UI。
- `conftest.py` 提供 fixtures；`core` 层可脱离 Qt 单独跑（依赖以 mock 注入）。
- 运行：`pytest`（建议在隔离 venv 中执行，详见项目根 `requirements.txt`）。
