import os
import time
from datetime import datetime
from typing import List, Optional
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from utils.database_manager import DatabaseManager
from tools.toolkits import StockToolkit, SearchToolkit, NewsToolkit
from prompts.fin_agent import (
    get_fin_researcher_instructions, 
    get_fin_analyst_instructions,
    get_fin_research_task,
    format_research_context,
    get_fin_analysis_task
)
from schema.models import InvestmentSignal, ResearchContext
from utils.json_utils import extract_json

class FinAgent:
    """
    金融分析师 (FinAgent) - 负责深度分析金融信号并关联具体的投资标的
    采用双模型架构：Tool Model 负责信息检索，Reasoning Model 负责深度分析与结构化输出。
    """
    
    def __init__(self, db: DatabaseManager, model: Model, tool_model: Optional[Model] = None, isq_template_id: str = "default_isq_v1"):
        self.db = db
        self.model = model  # Reasoning Model
        self.tool_model = tool_model or model  # Tool Model
        self.isq_template_id = isq_template_id
        
        # 初始化工具包
        self.stock_toolkit = StockToolkit(db)
        self.search_toolkit = SearchToolkit(db)
        self.news_toolkit = NewsToolkit(db)
        
        # 1. 研究员 Agent (负责使用工具搜集信息)
        self.researcher = Agent(
            model=self.tool_model,
            tools=[
                self.stock_toolkit.search_ticker,
                self.stock_toolkit.get_stock_price,
                self.search_toolkit.web_search,
                self.news_toolkit.fetch_news_content,
            ],
            instructions=[get_fin_researcher_instructions()],
            markdown=True,
            debug_mode=True,
            output_schema=ResearchContext if hasattr(self.tool_model, 'response_format') else None
        )

        # 2. 分析师 Agent (负责深度逻辑推理和 JSON 输出)
        self.analyst = Agent(
            model=self.model,
            instructions=[get_fin_analyst_instructions(template_id=self.isq_template_id)],
            markdown=True,
            debug_mode=True,
            output_schema=InvestmentSignal if hasattr(self.model, 'response_format') else None
        )
        
        logger.info(f"💼 FinAgent initialized (Dual-Model: Reasoning={self.model.id}, Tool={self.tool_model.id}, ISQ={self.isq_template_id})")

    def analyze_signal(self, signal_text: str, news_id: str = None, max_retries: int = 3) -> Optional[InvestmentSignal]:
        """
        分析具体的金融信号并返回结构化的 InvestmentSignal
        采用双模型架构：Tool Model 搜集数据 -> Reasoning Model 深度分析
        """
        
        logger.info(f"💼 FinAgent starting dual-phase analysis for: {signal_text[:50]}...")
        
        # 第一阶段：研究员搜集信息（使用 Tool Model）
        research_task = get_fin_research_task(signal_text)
        research_context_str = ""
        research_raw_response = ""
        
        try:
            logger.info("📊 Phase 1: Researcher gathering information using tools...")
            research_response = self.researcher.run(research_task)
            research_raw_response = research_response.content if hasattr(research_response, 'content') else str(research_response)
            
            # 直接使用研究员的完整输出（包含工具调用结果）
            research_context_str = research_raw_response
            
            # 同时尝试解析结构化数据用于日志记录
            research_data = extract_json(research_raw_response)
            if research_data:
                logger.info(f"✅ Research phase completed. Found tickers: {research_data.get('tickers_found', [])}")
            else:
                logger.info("✅ Research phase completed (unstructured format)")
                
        except Exception as e:
            logger.warning(f"⚠️ Research phase failed: {e}. Proceeding with raw signal only.")
            research_context_str = "（研究阶段失败，将仅基于原始信号进行分析）"

        # 第二阶段：分析师基于完整背景进行深度分析（使用 Reasoning Model）
        # 包含详细的工具调用结果和原始信号
        analysis_task = get_fin_analysis_task(signal_text, research_context_str)
        
        logger.info("🧠 Phase 2: Analyst performing deep ISQ analysis...")
        
        for attempt in range(max_retries):
            try:
                response = self.analyst.run(analysis_task)
                content = response.content if hasattr(response, 'content') else str(response)
                
                # 调试日志：显示分析师的输出长度
                logger.debug(f"Analyst response length: {len(content)} chars")
                
                # 尝试从内容中提取 JSON
                json_data = extract_json(content)
                if json_data:
                    # 补全 news_id 如果有
                    if news_id and not json_data.get('signal_id'):
                        json_data['signal_id'] = news_id
                    
                    logger.info(f"✅ Analysis completed successfully (attempt {attempt + 1}/{max_retries})")
                    logger.debug(f"Extracted signal: {json_data.get('title', 'N/A')}, confidence: {json_data.get('confidence', 'N/A')}")
                    
                    # 转换为模型对象
                    return InvestmentSignal(**json_data)
                
                raise ValueError("Could not extract valid JSON from response")
                
            except Exception as e:
                logger.warning(f"⚠️ FinAgent analysis attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                else:
                    logger.error("❌ FinAgent analysis failed after all retries")
                    return None

    def run(self, task: str) -> str:
        """通用运行入口 - 使用分析师 Agent 执行任务"""
        response = self.analyst.run(task)
        return response.content if hasattr(response, 'content') else str(response)

