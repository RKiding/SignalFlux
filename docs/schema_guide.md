┌─────────────────────────────────────────────────────────────┐
│                    Domain Layer（领域层）                     │
│  - FinancialAnalysis, StockData, ChartData 等业务对象         │
├─────────────────────────────────────────────────────────────┤
│                    Agent Layer（Agent层）                    │
│  - AgentInput, AgentOutput, AgentState 等通用接口             │
├─────────────────────────────────────────────────────────────┤
│                  Execution Layer（执行层）                   │
│  - Context, ExecutionLog, Step, Plan 等执行管理              │
├─────────────────────────────────────────────────────────────┤
│                  Configuration Layer（配置层）               │
│  - AgentConfig, ModelConfig 等配置管理                       │
└─────────────────────────────────────────────────────────────┘

