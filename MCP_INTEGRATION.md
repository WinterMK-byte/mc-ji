# MCP 接入说明

本文说明「麦记 · 营养手账」实际使用了麦当劳 MCP 的哪些能力、怎么调用、以及这些调用带来了什么业务价值。

---

## 1. MCP Server

| 项 | 值 |
|---|---|
| 服务 | 麦当劳中国 MCP Server |
| 接入地址 | `https://mcp.mcd.cn` |
| 开放平台 | <https://open.mcd.cn/mcp> |
| 传输协议 | Streamable HTTP |
| 认证方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 协议版本 | `2025-03-26` |
| 限流 | 每 Token 每分钟 600 次请求；超出返回 `429` |
| 错误码 | `401` Token 无效/过期；`429` 触发限流 |

客户端实现：`tools/mcd_mcp.py`。**纯 Python 标准库**，不依赖官方 SDK，便于任何人 clone 后直接运行。

它实现了 MCP 的四个必要环节：

| 环节 | 报文 | 说明 |
|---|---|---|
| 握手 | `initialize` | 携带 `protocolVersion` / `clientInfo`；服务端可能在响应头下发 `Mcp-Session-Id` |
| 确认 | `notifications/initialized` | 通知类报文，无 `id`，服务端返回空体 |
| 发现 | `tools/list` | 取得工具清单与 `inputSchema` |
| 调用 | `tools/call` | 参数 `{name, arguments}`，结果在 `content[]` 中 |

**双格式兼容**：服务端响应可能是 `application/json`，也可能是 `text/event-stream`（SSE）。客户端两种都解析——SSE 模式下逐行提取 `data:` 并取最后一条可解析消息。

---

## 2. 实际使用的 Tool

### 2.1 主链路（必须有）

| Tool | 中文名 | 本项目用途 | 调用参数 |
|---|---|---|---|
| `list-nutrition-foods` | 餐品营养信息列表 | 取得餐品的能量、蛋白质、脂肪、碳水化合物、钠，是「今日餐盘」全部数值的来源 | 无参（空对象） |

### 2.2 辅助链路（有则更好，失败不影响主流程）

| Tool | 中文名 | 本项目用途 | 调用参数 |
|---|---|---|---|
| `query-my-coupons` | 我的优惠券 | 在餐品列表下方显示「手上的券」，提醒快过期的券 | 无参 |
| `available-coupons` | 可用优惠券 | `query-my-coupons` 返回为空时的备选数据源 | 无参 |

### 2.3 未使用但已预留的 Tool

以下工具在当前版本未调用，代码中保留了接入位，属于后续迭代方向：

| Tool | 预留用途 |
|---|---|
| `query-meals` / `query-meal-detail` | 补充餐品分类与详情图，让餐品列表分组展示 |
| `calculate-price` | 用官方算价结果替换本地价格字段 |
| `query-nearby-stores` | 记录「在哪家店吃的」，适合经常换门店的用户 |

---

## 3. 调用流程

```
用户操作                     本地程序                             麦当劳 MCP
────────────────────────────────────────────────────────────────────────────
配好 MCD_MCP_TOKEN
运行 sync_nutrition.py
        │
        ├── 1. initialize ──────────────────────────────────▶ 返回 serverInfo
        │                                                     + Mcp-Session-Id
        ├── 2. notifications/initialized ───────────────────▶ 202 空体
        │
        ├── 3. tools/call  list-nutrition-foods ────────────▶ 餐品营养数据
        │      └─ 原始返回落盘 data/raw_nutrition.json
        │      └─ normalize_item() 容错解析字段
        │
        ├── 4. tools/call  query-my-coupons ────────────────▶ 券列表
        │      └─ 为空则再试 available-coupons
        │
        ├── 5. 组装 payload {source:"mcp", items[], coupons[]}
        │
        ├── 6. 写入 data/nutrition_snapshot.json
        │
        └── 7. 正则替换 mc_ji.html 里的
               <script id="nutrition-data" type="application/json">
                    │
双击打开 mc_ji.html ────────┘
        └── 前端读内嵌 JSON → 渲染餐品列表 / 累计营养 / 券
            用户在「今日餐盘」选餐 → 一键写入 Markdown 日记
```

### 为什么是「脚本拉取 + 内嵌注入」而不是「前端直连 MCP」

| 方案 | 问题 |
|---|---|
| HTML 里直接 `fetch('https://mcp.mcd.cn')` | ① 浏览器 CORS 不允许 ② Token 会暴露在前端源码里 ③ `file://` 下直接被拦 |
| 起一个本地后端转发 | 要多跑一个进程，违背「双击就开」的使用习惯 |
| **脚本拉取 + 内嵌注入（本项目）** | 数据是静态快照，**Token 只存在环境变量里，永不进 HTML**；界面仍然单文件、零依赖、可离线 |

这个取舍的代价是「数据不是每秒实时」——但对一个饮食记录工具，一天同步一次完全够用。

---

## 4. 字段映射与容错

麦当劳 MCP 的返回字段名可能随迭代调整，因此 `normalize_item()` 对每个字段做**多别名探测**（先精确匹配，再大小写无关匹配）：

| 内部字段 | 尝试的字段名 | 类型 |
|---|---|---|
| 名称 | `name` / `productName` / `mealName` / `title` / `cnName` / `餐品名称` / `名称` | str |
| 编码 | `code` / `productCode` / `sku` / `id` / `mealCode` | str |
| 热量 | `energy` / `energyKcal` / `kcal` / `calorie` / `calories` / `热量` / `能量` | number |
| 蛋白质 | `protein` / `proteinG` / `蛋白质` | number |
| 脂肪 | `fat` / `fatG` / `脂肪` | number |
| 碳水 | `carbohydrate` / `carb` / `carbG` / `碳水` / `碳水化合物` | number |
| 钠 | `sodium` / `sodiumMg` / `钠` | number |
| 价格 | `price` / `priceCny` / `salePrice` / `价格` | number |

**数值提取**：若字段是 `"550 kcal"` 这类带单位字符串，用正则取数字部分，避免解析失败。

**响应结构兼容**：MCP 的 `content[].text` 可能是 JSON 字符串（还可能被 markdown 代码块包了一层）。`load_payload_text()` 依次尝试：直接 `json.loads` → 剥掉 ```` ``` ```` 围栏再解析 → 从 `data` / `items` / `list` / `foods` / `meals` / `products` 等常见键里找数组。

**兜底策略**：任何一步失败，都退回离线快照并**在界面上明示**「○ 离线演示快照」，绝不用演示值冒充实时值。原始返回同时落盘 `data/raw_nutrition.json`，方便日后对照修复。

---

## 5. 业务价值

| 价值点 | 具体体现 |
|---|---|
| **把一次性查询变成长期数据** | 用户查一次营养是瞬时行为；麦记把它写进 Markdown 日记，形成可回看的饮食档案 |
| **降低记录成本** | 从「打开 App → 搜索餐品 → 记录」压缩成「点几个 + → 写入日记」，全程在自己熟悉的编辑器里 |
| **让营养数据进入文本工作流** | 输出是标准 Markdown 表格，可被任何笔记软件、知识库、版本管理工具消费 |
| **隐私优先** | Token 只在本地环境变量；草稿与餐盘数据只存 `localStorage`；不上传任何用户数据 |
| **可离线** | 断网、无 Token 时仍是完整可用的 Markdown 手账，MCP 只是增强而非依赖 |

---

## 6. 如何自行验证

```bash
# ① 只验证 MCP 连通性与工具清单
python tools/mcd_mcp.py check

# ② 看会拉到什么（不改文件）
python tools/sync_nutrition.py --dry

# ③ 真拉一次并写入
python tools/sync_nutrition.py

# ④ 单独调某个工具看原始返回
python tools/mcd_mcp.py call list-nutrition-foods "{}"
```

成功标志：`mc_ji.html` 顶部标签由「○ 离线演示快照」变为「● 麦当劳 MCP 实时」。

---

## 7. 合规说明

- 本项目的 MCP Token **不硬编码、不进版本库**，只从环境变量 `MCD_MCP_TOKEN` 读取；仓库内 `mcp-config.example.json` 全部使用占位符。
- 营养参考值为一般成人估算，**不构成医疗或营养建议**。
- 餐品、价格、供应状态以麦当劳官方渠道的实时结果为准。
- 本项目为参赛作品，非麦当劳官方产品。
