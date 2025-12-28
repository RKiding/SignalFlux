import os
from agno.agent import Agent
from agno.models.base import Model
from typing import List, Optional
from loguru import logger

from utils.database_manager import DatabaseManager
from tools.toolkits import NewsToolkit, StockToolkit, SentimentToolkit, SearchToolkit, PolymarketToolkit
from prompts.trend_agent import get_trend_agent_instructions

# 从环境变量读取默认配置
DEFAULT_SENTIMENT_MODE = os.getenv("SENTIMENT_MODE", "auto")


class TrendAgent:
    """
    趋势挖掘 Agent - 负责在全网范围内捕抓金融信号
    
    使用 Agno 原生 Function Calling，需要模型支持工具调用（如 qwen2.5, gpt-4 等）
    
    功能:
    - 扫描多平台热点新闻（微博、知乎、财联社、华尔街见闻等）
    - 过滤并识别具有金融价值的信号
    - 关联相关股票代码和行业
    - 进行情绪分析和信号强度评估
    """
    
    def __init__(self, db: DatabaseManager, model: Model, sentiment_mode: Optional[str] = None):
        """
        初始化趋势挖掘 Agent。
        
        Args:
            db: 数据库管理器实例
            model: LLM 模型实例（需支持 Function Calling）
            sentiment_mode: 情绪分析模式，可选 "auto", "bert", "llm"。
                           None 则使用环境变量 SENTIMENT_MODE 或默认 "auto"。
        """
        self.db = db
        self.model = model
        
        # 使用传入的模式或环境变量默认值
        effective_sentiment_mode = sentiment_mode or DEFAULT_SENTIMENT_MODE
        
        # 初始化 Toolkit 层
        self.news_toolkit = NewsToolkit(db)
        self.stock_toolkit = StockToolkit(db)
        self.sentiment_toolkit = SentimentToolkit(db, mode=effective_sentiment_mode)
        self.search_toolkit = SearchToolkit(db)
        self.polymarket_toolkit = PolymarketToolkit(db)
        
        logger.info(f"🔧 TrendAgent initialized with sentiment_mode={effective_sentiment_mode}")
        
        # 获取带有实时时间的指令
        instructions = get_trend_agent_instructions()
        
        # 构建 Agno Agent，注册 Toolkits
        self.agent = Agent(
            model=self.model,
            instructions=[instructions],
            tools=[
                self.news_toolkit,
                self.stock_toolkit,
                self.sentiment_toolkit,
                self.search_toolkit,
                self.polymarket_toolkit,
            ],
            markdown=True
        )

    def run(self, task_description: str = "分析当前全网热点，找出最有价值的三个金融信号"):
        """
        执行趋势发现任务。
        
        Args:
            task_description: 任务描述，指导 Agent 的分析方向。
        
        Returns:
            Agent 的响应对象，包含分析结果。
        """
        logger.info(f"🚀 TrendAgent starting task: {task_description}")
        return self.agent.run(task_description)


    def discover_daily_signals(self, focus_sources: Optional[List[str]] = None):
        """
        执行每日例行信号扫描。
        
        Args:
            focus_sources: 重点扫描的新闻源列表。默认扫描财联社、华尔街见闻。
        
        Returns:
            Agent 的响应对象。
        """
        sources = focus_sources or ["cls", "wallstreetcn"]
        sources_str = "、".join(sources)
        
        prompt = f"""执行基于 ISQ (投资信号质量) 框架的每日金融扫描：

1. **多维采集**: 使用 fetch_hot_news 获取 {sources_str} 等平台热点。
2. **FSD 过滤**: 识别具有高“金融信号密度”的内容，过滤掉纯娱乐或宽泛社会新闻。
3. **初步 ISQ 评估**:
   - 评估信号的**强度(Intensity)**：它对相关行业是边际影响还是结构性重塑？
   - 评估信号的**确定性(Confidence)**：是确认的消息还是传闻？
4. **逻辑初步构建**: 尝试识别该信号可能的传导链条（如：原材料上涨 -> 电池成本上升 -> 乘用车提价）。
5. **输出**: 生成一份结构化的每日信号清单，重点标注 FSD 评分最高的 3-5 个核心信号。
"""
        return self.run(prompt)
