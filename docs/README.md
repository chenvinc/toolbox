> 📥 **下载最新版 (v4.1)：[toolbox_AllInOne_v4.1.exe](https://github.com/chenvinc/toolbox/releases/download/v4.1/toolbox_AllInOne_v4.1.exe)** ｜ [全部 Release](https://github.com/chenvinc/toolbox/releases)

# docs/ 文档索引（v4.1）

| 文件 | 说明 |
| --- | --- |
| [architecture.md](./architecture.md) | **项目架构书 v4.1** — 分层、端口与适配器、数据流、五大工具、UI 规范、主题系统、技术债 |
| [新增Tool开发指南.md](./新增Tool开发指南.md) | **新增 Tool 开发指南 v4.1** — 从契约到注册的端到端步骤、可复制模板与避坑清单 |
| [archive/](./archive/) | 历史整改/阶段报告与早期原型（仅供追溯，不参与当前架构） |

## 功能使用说明

工具箱内置 **5 个工具**，均在左侧导航切换。通用操作：**选择输入文件**（点击或拖拽到虚线框）→（可选）**套用模板** → **设置输出路径** → 点「开始转换 / 生成」→ 完成后点「打开文件夹」取结果。

| 工具 | 用途 | 输入 | 输出 | 简要步骤 |
| --- | --- | --- | --- | --- |
| 📑 题库转PPT（Quiz2Slide） | Word 题目文档 → 可编辑 PPT | 1 个 `.docx` 题库 | `.pptx` | 导入题库 → 预览/确认解析出的题目 →（可选）选 PPT 模板 → 生成 |
| 🔍 试题查重（SimilarityChecker） | 题目相似度比对，导出报告 | 主文档 `.docx` + 副文档（可多选 `.docx`），或切「多对多」拖入多份 | 查重报告 `.docx` | 选主文档与副文档（或多对多模式拖入多份）→ 设阈值 → 开始查重 → 导出报告 |
| 📝 试卷生成（JsonExam） | JSON 题目数据（需配合fbdll插件使用） → Word 题本 + 解析 | 1 个 `.json` | 题本 `.docx` + 解析 `.docx` | 导入 JSON → 设题号格式 / 首行缩进等 → 生成题本与解析 |
| 📄 PDF转PPT（Pdf2Slide） | PDF 每页 → 保留可编辑文字的 PPT | 1 个 `.pdf`（可选 `.pptx` 模板） | `.pptx` | 导入 PDF →（可选）套 PPT 模板 → 设输出路径 → 转换 |
| 📄 PDF转Word（Pdf2Word） | PDF → 保留可编辑文字（流式段落）的 Word | 1 个 `.pdf`（可选 `.docx` 模板） | `.docx` | 导入 PDF →（可选）套 Word 模板 → 设输出路径 → 转换 |

> 说明：
> - **模板为可选项**：套用后输出沿用模板的版式 / 样式骨架并写入转换结果（模板原有正文会被清空）；不套模板则使用默认样式。
> - **输出路径**默认落在输入文件同目录，可手动修改；若与源文件 / 模板同名同目录会被拦截（防覆盖）。
> - 进度与结果经统一事件通道回流，完成后视图内提供「打开文件夹」链接。

## 约定
- 架构与设计以 `architecture.md` 为准；新增工具照 `新增Tool开发指南.md` 执行。
- `core/` 与 `shared/` 保持零 Qt 依赖。
- 所有后台进度/完成/失败统一走 `DomainEvent` + 唯一 `EventEmitter`；每个工具使用专属 `EventType`。
