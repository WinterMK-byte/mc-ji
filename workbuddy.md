# WorkBuddy 开发对话纪要

> 本项目使用腾讯 WorkBuddy 开发完成。本文是开发过程的对话纪要，用于核验 WorkBuddy 联动活动参与条件。

## 一、任务缘起

参赛者提出需求：把此前自己做的单文件 Markdown 手账（「墨记」）改造为一个能对接麦当劳 MCP 的参赛作品。

## 二、WorkBuddy 在本次开发中实际完成的工作

| 阶段 | 内容 |
|---|---|
| 1. 规则研读 | 读取官方仓库 `M-China/mcd-developer-innovation-challenge` 的 README 与 `activityGuidelines.md`，整理出必需文件清单（README / CONTEST_DECLARATION / MCP_INTEGRATION / mcp-config.example.json / workbuddy.md）与截止时间 |
| 2. 能力盘点 | 读取 `M-China/mcd-mcp-server` 文档，提取全部 33 个 MCP Tool 的中英文名与用途，确定哪些与「饮食记录」场景匹配 |
| 3. 协议验证 | 手写纯标准库 MCP 客户端，向 `https://mcp.mcd.cn` 发 `initialize` 探测，确认服务端返回 401 与中文错误提示，验证接入地址与报文格式正确 |
| 4. 方案设计 | 确定「脚本拉取 + 内嵌注入」架构：避开浏览器 CORS 与 Token 泄露风险，同时保留单文件双击可用的体验 |
| 5. 代码改造 | 在原 575 行手账 HTML 上做锚点插入（新增 tab、面板、CSS、JS），保留原有 Markdown 解析器与草稿逻辑 |
| 6. 数据层 | 编写 `mcd_mcp.py`（JSON-RPC + SSE 双格式解析）与 `sync_nutrition.py`（字段多别名容错 + 离线兜底） |
| 7. 自检 | HTML 标签配对检查、JS 语法检查（Node）、离线数据注入验证、声明文件与官方 md5 比对 |

## 三、技术取舍记录

- **不用官方 SDK**：改用手写标准库客户端，让 clone 者无需 `pip install` 即可验证 MCP 连通性。
- **不前端直连 MCP**：浏览器 CORS + Token 暴露 + `file://` 拦截三重问题，改为脚本拉取后内嵌静态数据。
- **离线快照必须显式标注**：演示值不能冒充官方实时值，界面顶部用不同颜色区分「● 实时」与「○ 离线」。

## 四、说明

本文为开发过程纪要，非逐字对话导出。原始完整对话可由参赛者从 WorkBuddy 客户端导出后替换本文件。
