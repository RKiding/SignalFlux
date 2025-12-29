# ISQ 模板配置目录

本目录存放所有 ISQ (Investment Signal Quality) 评估模板的配置文件。

## 目录结构

```
config/
├── README.md           # 本文件
├── default.json        # 默认标准模板
├── short_term.json     # 短线交易模板
├── macro.json          # 宏观政策模板
└── risk.json           # 风险监测模板
```

## 使用方法

### 1. 选择模板

在 `main_flow.py` 中指定模板 ID：

通过命令行参数：

```bash
# 默认模板
uv run src/main_flow.py

# 短线模板
uv run src/main_flow.py --template=isq_short_term_v1

# 宏观模板
uv run src/main_flow.py --template=isq_macro_v1

# 风险模板
uv run src/main_flow.py --template=isq_risk_v1
```

### 2. 修改现有模板

直接编辑对应的 JSON 文件即可。修改后重启程序生效。

例如，修改默认模板的权重：

```json
{
  "dimension_weights": {
    "confidence": 0.40,      // 提高确定性权重
    "intensity": 0.30,
    "expectation_gap": 0.20,
    "timeliness": 0.10       // 降低时效性权重
  }
}
```

### 3. 创建新模板

在本目录下创建新的 JSON 文件（如 `custom.json`），结构参考已有模板：

```json
{
  "template_id": "isq_custom_v1",
  "template_name": "自定义 ISQ 模板",
  "description": "根据特定需求定制的评估框架",
  "dimensions": {
    "sentiment": { ... },
    "confidence": { ... },
    "intensity": { ... },
    "expectation_gap": { ... },
    "timeliness": { ... }
  },
  "scoring_guide": "评分指导说明",
  "applicable_scenarios": ["场景1", "场景2"],
  "aggregation_method": "weighted_average",
  "dimension_weights": {
    "confidence": 0.35,
    "intensity": 0.30,
    "expectation_gap": 0.20,
    "timeliness": 0.15
  }
}
```

程序启动时会自动加载目录下的所有 `.json` 文件。

## 预配置模板说明

### default.json - 标准模板
- **适用场景**：通用投资信号分析
- **权重分配**：确定性 35%、强度 30%、预期差 20%、时效性 15%
- **特点**：平衡各维度，适合大多数场景

### short_term.json - 短线交易
- **适用场景**：高频交易、突发事件、盘中热点
- **权重分配**：时效性 30%、强度 30%、确定性 20%
- **特点**：强调快速反应和影响力度

### macro.json - 宏观政策
- **适用场景**：政策分析、宏观研究、行业趋势
- **权重分配**：确定性 35%、预期差 25%、强度 20%
- **特点**：重视政策落地确定性和市场定价缺口

### risk.json - 风险监测
- **适用场景**：风险事件、黑天鹅、下行压力
- **权重分配**：确定性 35%、强度 30%、时效性 20%
- **特点**：关注风险冲击强度和兑现速度

## 技术说明

- **加载机制**：程序启动时自动扫描本目录下的所有 `.json` 文件
- **热更新**：不支持，修改后需重启程序
- **容错处理**：单个文件解析失败不影响其他模板加载
- **默认回退**：如果指定的模板不存在，自动使用 `default_isq_v1`

## 字段说明

### 必填字段

- `template_id`: 模板唯一标识（字符串）
- `template_name`: 模板显示名称
- `description`: 模板描述
- `dimensions`: 5 个维度定义（sentiment, confidence, intensity, expectation_gap, timeliness）
- `dimension_weights`: 各维度权重（总和建议为 1.0）

### 维度定义

每个维度包含：
- `name`: 维度名称
- `key`: 维度键（必须与 dimensions 中的 key 一致）
- `description`: 维度说明
- `range_type`: 取值范围描述
- `scale_factor`: 缩放因子（通常为 1.0 或 20.0）
- `examples`: 取值示例（字典）
- `visualization_color`: 可视化颜色（可选，用于雷达图）

### 可选字段

- `scoring_guide`: 评分指导文本
- `applicable_scenarios`: 适用场景列表
- `aggregation_method`: 聚合方法（默认 weighted_average）

## 故障排查

### 模板未加载

1. 检查 JSON 格式是否正确（使用 JSON 验证工具）
2. 确认文件扩展名为 `.json`
3. 查看程序启动日志是否有错误提示

### 模板加载但无效

1. 确认 `template_id` 拼写正确
2. 检查权重总和是否合理
3. 验证所有必填字段是否存在

### 需要调试信息

可临时修改 `src/schema/isq_template.py` 中的 `load_templates_from_config` 函数，
添加 print 语句查看加载过程。
