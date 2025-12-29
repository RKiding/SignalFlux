import os
from agno.agent import Agent
from agno.models.base import Model
from typing import List, Optional
from loguru import logger

from utils.database_manager import DatabaseManager
from tools.toolkits import NewsToolkit, StockToolkit, SentimentToolkit, SearchToolkit, PolymarketToolkit
from prompts.trend_agent import (
    get_trend_scanner_instructions, 
    get_trend_evaluator_instructions,
    get_trend_scan_task,
    format_scan_context,
    get_trend_eval_task
)
from schema.models import ScanContext
from utils.json_utils import extract_json

# 从环境变量读取默认配置
DEFAULT_SENTIMENT_MODE = os.getenv("SENTIMENT_MODE", "auto")


class TrendAgent:
    """
    趋势挖掘 Agent - 负责在全网范围内捕抓金融信号
    采用双模型架构：Tool Model 负责数据采集，Reasoning Model 负责信号筛选与价值评估。
    """
    
    def __init__(self, db: DatabaseManager, model: Model, tool_model: Optional[Model] = None, sentiment_mode: Optional[str] = None):
        """
        初始化趋势挖掘 Agent。
        
        Args:
            db: 数据库管理器实例
            model: Reasoning Model (用于筛选和评估)
            tool_model: Tool Model (用于执行工具调用)
            sentiment_mode: 情绪分析模式
        """
        self.db = db
        self.model = model
        self.tool_model = tool_model or model
        
        # 使用传入的模式或环境变量默认值
        effective_sentiment_mode = sentiment_mode or DEFAULT_SENTIMENT_MODE
        
        # 初始化 Toolkit 层
        self.news_toolkit = NewsToolkit(db)
        self.stock_toolkit = StockToolkit(db)
        self.sentiment_toolkit = SentimentToolkit(db, mode=effective_sentiment_mode)
        self.search_toolkit = SearchToolkit(db)
        self.polymarket_toolkit = PolymarketToolkit(db)
        
        logger.info(f"🔧 TrendAgent initialized (Dual-Model: Reasoning={self.model.id}, Tool={self.tool_model.id})")
        
        # 1. 扫描员 Agent (负责执行工具调用获取原始数据)
        self.scanner = Agent(
            model=self.tool_model,
            tools=[
                self.news_toolkit,
                self.stock_toolkit,
                self.sentiment_toolkit,
                self.search_toolkit,
                self.polymarket_toolkit,
            ],
            instructions=[get_trend_scanner_instructions()],
            markdown=True,
            output_schema=ScanContext if hasattr(self.tool_model, 'response_format') else None
        )

        # 2. 评估员 Agent (负责对扫描到的数据进行价值判断)
        self.evaluator = Agent(
            model=self.model,
            instructions=[get_trend_evaluator_instructions()],
            markdown=True
        )

    def run(self, task_description: str = "分析当前全网热点，找出最有价值的三个金融信号"):
        """
        执行趋势发现任务。
        """
        logger.info(f"🚀 TrendAgent starting task: {task_description}")
        
        # 第一阶段：扫描数据（使用 Tool Model 调用工具获取原始数据）
        logger.info("📡 Phase 1: Scanner executing tool calls...")
        scan_prompt = get_trend_scan_task(task_description)
        scan_response = self.scanner.run(scan_prompt)
        scan_raw_content = scan_response.content if hasattr(scan_response, 'content') else str(scan_response)
        
        logger.debug(f"Scanner output length: {len(scan_raw_content)} chars")
        
        # 尝试解析为 ScanContext 以提取结构化数据
        scan_data = extract_json(scan_raw_content)
        # 使用完整的扫描输出（包含所有工具调用结果），而不是格式化版本
        raw_data_str = scan_raw_content if scan_raw_content else "无法获取扫描数据"
        
        logger.info(f"✅ Scanning phase completed. Data length: {len(raw_data_str)} chars")
        
        # 第二阶段：评估价值（使用 Reasoning Model 进行深度分析）
        logger.info("🧠 Phase 2: Evaluator analyzing scan results...")
        eval_prompt = get_trend_eval_task(task_description, raw_data_str)
        return self.evaluator.run(eval_prompt)


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
