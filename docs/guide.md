# SignalFlux 架构与执行指南 (Architecture & Execution Guide)

本项目是一个基于多智能体（Multi-Agent）协作的金融情报系统。它通过捕捉全网热点（新闻/社交媒体），提取潜在金融信号，结合实时股价数据进行深度分析，并最终生成具备可视化图表的专业研报。

---

## 1. 架构概览 (Architecture Overview)

SignalFlux 采用**分层架构**设计，确保了工具集（Tools）、大脑（Agents）与工作流（Workflow）的解耦。

### 1.1 三层架构模型
1.  **工作流层 (Workflow Layer - `main_flow.py`)**: 
    - 负责全局状态管理与智能体编排。
    - 实现任务的具体执行路径：意图识别 -> 热点发现 -> 深度分析 -> 研报生成。
2.  **智能体层 (Agent Layer - `src/agents/`)**: 
    - 基于 **Agno (原 Phidata)** 框架构建，原生支持 Function Calling。
    - 包含：`TrendAgent` (情报官)、`FinAgent` (分析师)、`ReportAgent` (主编)、`IntentAgent` (意图解析器)。
3.  **基础设施与工具层 (Infra & Tools - `src/utils/`, `src/tools/`)**:
    - **Toolkit**: 为 Agent 封装的工具包（News, Stock, Sentiment, Search, Polymarket）。
    - **Utils**: 底层物理实现，包括 SQLite 数据库管理、Jina 内容抓取、BERT/LLM 情感分析算法。

### 1.2 数据流向 (Data Flow)
`User Query` -> `IntentAgent` (解析搜索词) -> `TrendAgent` (抓取多源热点 & 搜索) -> `Logic Filter` (LLM 智能筛选信号) -> `FinAgent` (关联标的、分析逻辑、检查股价) -> `ReportAgent` (Map-Reduce 模式分段撰写与编辑) -> `Markdown/HTML Report`.

---

## 2. 详细技术实现方案

### 2.1 核心智能体链条
*   **TrendAgent**: 
    - 使用 `NewsToolkit` 接入微博、知乎、财联社、华尔街见闻等 15+ 数据源。
    - 利用 `SentimentToolkit` 快速计算海量短文本的情感分值。
*   **FinAgent**: 
    - 负责推理。它会自动搜索公司财报或新闻，通过 `StockToolkit` 验证股票代码（Akshare 驱动）。
    - **容错设计**：如果 `search_ticker` 失败，它会尝试简化关键词重新搜索。
*   **ReportAgent (关键特性)**:
    - 采用 **Map-Reduce / Plan-Write-Edit** 设计。
    - **Plan**: 主编规划整篇大纲。
    - **Write**: 针对每个信号独立生成章节，并生成特殊的 `json-chart` 配置块。
    - **Edit**: 增量编辑模式。通过 **Hybrid-RAG (BM25 + Vector Search)** 实现跨章节上下文检索，确保研报逻辑的严密性。

### 2.2 统一混合检索引擎 (Unified Hybrid RAG Engine)
为了消除模块间检索逻辑的碎片化（如 `ContextSearchToolkit` 的关键词匹配与 `DatabaseManager` 的 SQL 搜索），建议抽象出统一的混合检索层：
*   **BM25 (文本召回)**: 负责精确匹配专有名词（股票代码、高管姓名、政策文号）。
*   **Embedding (语义召回)**: 负责模糊概念匹配（如“清洁能源”关联到“光伏/风能”）。
*   **共享实现**: 
    - `ContextSearchToolkit` (内存态 RAG): 动态加载研报章节草稿。
    - `LocalNewsSearch` (持久态 RAG): 检索数据库中的历史新闻。

### 2.3 从“情绪分析”向“信号解析”演进 (From Sentiment to Signal Intelligence)
传统的 Sentiment Score (-1.0 到 1.0) 在专业研报中往往过于笼统且缺乏操作指导性。我们建议将单一分值解构为**多维信号矩阵 (ISQ - Investment Signal Quality)**：

1.  **传导链条 (Transmission Chain)**: 事件 -> 行业影响 -> 财务指标损益 -> 估值重塑（而非仅仅是“好”或“坏”）。
2.  **信号强度与确定性 (Intensity & Confidence)**: 
    - **强度**: 是一次性扰动（Noise）还是结构性突变（Structural Shift）？
    - **分值确定性**: 基于聚合搜索的一致性评分。
3.  **预测视角 (Expectation Management)**:
    - **反应时窗**: 预计该信号在 T+0 还是 T+N 反应在股价上。
    - **预期差管理**: 市场是否已经提前交易（Price-in）？

### 2.4 存储与缓存策略
*   **SQLite 持久化**: 存储所有抓取的新闻、已生成的信号分析、以及股价历史。
*   **搜索缓存 (Search Cache)**: `SearchTools` 内置了基于 Hash 的缓存机制，同一个关键词的搜索结果在 TTL（默认 1 小时）内不会重复调用 API，显著降低延迟和成本。
*   **分析缓存**: `main_flow.py` 在执行分析前会检查数据库是否存在该新闻的分析结果 (`cached_analysis`)，实现“增量式”报告生成。

---

## 3. 执行指南 (Execution Guide)

### 3.1 快速启动
1.  **环境配置**:
    - 在 `.env` 中配置 `LLM_PROVIDER`, `LLM_MODEL` 及具体的 API Key。
    - 配置 `OLLAMA_HOST` (如果使用本地模型)。
2.  **运行完整流**:
    ```bash
    # 进入 src 目录并执行
    python main_flow.py
    ```
    生成的报告会存放于 `reports/` 目录下，包含 `.md` 和 `.html` 格式。

### 3.2 关键参数说明 (`run`)
- `sources`: 选择数据源（'financial', 'social', 'tech', 'all'）。
- `wide`: 每个源抓取的广度（默认 10）。
- `depth`: 最终分析的信号数量限制。'auto' 代表由 LLM 自行根据价值判断。
- `query`: 特定查询（如“美股半导体走势”），会触发主动搜索模式。

---

## 4. 未来架构演进计划 (Future Plans)

结合目前的 `plans.md`，后续重点改进方向：

### 4.1 深度语义可视化 (Semantic Visualization)
- **关联拓扑图**: 弃用简单的词云，改为展示“事件-板块-个股”的**逻辑衍生图**，直观呈现信号的穿透力。
- **敏感度热力图**: 展示关键变量（如：汇率、油价、政策力度）对目标标的利润影响的压力测试结果。
- **舆情博弈分布**: 不再只提供均分，而是展示看多与看空观点的**分布熵**（Entropy），识别市场分歧点（Alpha 往往存在于分歧中）。

### 4.2 预测模型集成 (Advanced Inference)
- **Kronos 集成**: 接入 [Kronos](https://github.com/shiyu-coder/Kronos) 等预训练时序大模型。
- **AI 预测微调**: Agent 获取特定步长的模型预测结果，并在此基础上结合新闻信号进行多模态微调/修正。

### 4.3 智能信号漏斗与“精排”架构演进 (Advanced Signal Pipeline)

目前的筛选逻辑较为线性，主要依赖单次 LLM 调用。我们建议演进为更具工业感的**四阶段信号漏斗**：

1.  **多路召回 (Multi-Source Recall)**:
    - **静默监测**: 从 NewsNow (微博/财联社) 捕获“面”上的热点。
    - **主动深度搜索**: 针对潜在高价值词汇（如“低空经济”、“降准”）触发 SearchToolkit 进行全网扫荡。
    - **预测市场锚点**: 引入 Polymarket 赔率变化作为“热度系数”增益。

2.  **语义聚类与去重复 (Clustering & Deduplication)**:
    - 使用向量嵌入 (Embedding) 对召回的新闻进行密度聚类。
    - **核心逻辑**：不按 ID 过滤，而是按“事件流”过滤。同一事件的 10 条新闻只保留“信息增量”最大的一条（通常是首发或综述类）。

3.  **多维度加权精排 (Multi-Dimensional Expert Ranking)**:
    - 摒弃简单的“相关性”判断，引入 **FSD (Financial Signal Density)** 评分体系：
        - **相关性 (Relevance)**: 与用户意图或 A 股板块的紧密度。
        - **影响力 (Impact)**: 历史同类事件（通过 Vector DB 调取）触发后的平均涨幅系数。
        - **时效偏置 (Freshness)**: 权重随时间指数级衰减，优先处理“刚出炉”的长尾消息。
        - **逻辑强度 (Logical Coherence)**: LLM 评估该消息是否具备清晰的“原因-结果”闭环。
    - **进阶方案**：采用 **Pairwise (对战式) 评估**，将信号两两对比，解决 LLM 在面对长列表时出现的“位置偏差 (Positional Bias)”问题。

4.  **全局多样性重排 (Diversity & Coverage)**:
    - 采用 **MMR (Maximal Marginal Relevance)** 算法。
    - **目标**：保证最终生成的研报不仅覆盖“最热”的板块，也能涵盖“有潜力”的冷门板块，避免研报内容的严重同质化。

### 4.4 基础设施组件化 (Infra Componentization)
- **Hybrid Search Utility**: 将目前的碎片化搜索提取为 `src/utils/hybrid_search.py`。
    - 支持 `InMemoryStore` (用于研报编辑同步) 和 `SQLiteStore` (用于历史信号回溯)。
    - 实现 **Reciprocal Rank Fusion (RRF)** 算法，融合 BM25 与向量搜索的评分。
- **回测引擎**: 在生成报告 48 小时后，系统自动比对预测结论与实际股价表现。
- **负样本训练**: 将“预测错误”的信号标记为负样本，作为后续精排 Agent 的 Prompt 示例（In-context Learning），提升模型对“市场噪音”的识别能力。
- **知识库 (Mem0/VectorStore)**: 记录哪些关键词/行业在特定周期内具有更高的信号敏感度，动态调整召回权重。

### 4.4 框架升级
- **动态拓扑**: 考虑引入 **LangGraph** 处理更复杂的“回溯分析”和“自纠错”循环（如股价异常波动触发自动深挖原因）。
- **美股支持**: 扩展 `StockTools` 以支持 Alpha Vantage 或 Yahoo Finance 等 API 接入。

---
*Last Updated: 2025-12-27*