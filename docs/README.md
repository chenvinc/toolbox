# docs/ 文档索引（v4.0）

| 文件 | 说明 |
| --- | --- |
| [architecture.md](./architecture.md) | **项目架构书 v4.0** — 分层、端口与适配器、数据流、四大工具、UI 规范、主题系统、技术债 |
| [新增Tool开发指南.md](./新增Tool开发指南.md) | **新增 Tool 开发指南 v4.0** — 从契约到注册的端到端步骤、可复制模板与避坑清单 |
| [archive/](./archive/) | 历史整改/阶段报告与早期原型（仅供追溯，不参与当前架构） |

## 约定
- 架构与设计以 `architecture.md` 为准；新增工具照 `新增Tool开发指南.md` 执行。
- `core/` 与 `shared/` 保持零 Qt 依赖。
- 所有后台进度/完成/失败统一走 `DomainEvent` + 唯一 `EventEmitter`；每个工具使用专属 `EventType`。
