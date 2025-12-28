import os
from datetime import datetime
from typing import List, Optional
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from utils.database_manager import DatabaseManager
from tools.toolkits import StockToolkit, SearchToolkit, NewsToolkit
from prompts.fin_agent import get_fin_agent_instructions
from schema.models import InvestmentSignal
from utils.json_utils import extract_json

class FinAgent:
    """
    金融分析师 (FinAgent) - 负责深度分析金融信号并关联具体的投资标的
    """
    
    def __init__(self, db: DatabaseManager, model: Model):
        self.db = db
        self.model = model
        
        # 初始化工具包
        self.stock_toolkit = StockToolkit(db)
        self.search_toolkit = SearchToolkit(db)
        self.news_toolkit = NewsToolkit(db)
        
        # 构建 Agent 指令
        instructions = get_fin_agent_instructions()

        self.agent = Agent(
            model=self.model,
            instructions=[instructions],
            tools=[
                self.stock_toolkit.search_ticker,
                self.stock_toolkit.get_stock_price,
                self.search_toolkit.web_search,
                self.news_toolkit.fetch_news_content,
            ],
            markdown=True,
            debug_mode=True,
            # 强化 JSON 输出的稳定性
            output_schema=InvestmentSignal if hasattr(self.model, 'response_format') else None
        )
        
        logger.info("💼 FinAgent initialized")

    def analyze_signal(self, signal_text: str, news_id: str = None, max_retries: int = 3) -> Optional[InvestmentSignal]:
        """
        分析具体的金融信号并返回结构化的 InvestmentSignal
        """
        import time
        
        logger.info(f"💼 FinAgent analyzing signal: {signal_text[:50]}...")
        task = f"请详细分析以下金融信号，并按要求输出 JSON 表彰：\n\n{signal_text}"
        
        for attempt in range(max_retries):
            try:
                response = self.agent.run(task)
                content = response.content if hasattr(response, 'content') else str(response)
                
                content = response.content if hasattr(response, 'content') else str(response)
                
                # 尝试从内容中提取 JSON
                json_data = extract_json(content)
                if json_data:
                    # 补全 news_id 如果有
                    if news_id and not json_data.get('signal_id'):
                        json_data['signal_id'] = news_id
                    
                    # 转换为模型对象
                    return InvestmentSignal(**json_data)
                
                raise ValueError("Could not extract valid JSON from response")
                
            except Exception as e:
                logger.warning(f"⚠️ FinAgent attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error("❌ FinAgent analysis failed after all retries")
                    return None

    def run(self, task: str) -> str:
        """通用运行入口"""
        return self.agent.run(task)

