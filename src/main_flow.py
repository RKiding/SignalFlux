import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from loguru import logger
from dotenv import load_dotenv

from utils.database_manager import DatabaseManager
from utils.llm.factory import get_model
from utils.search_tools import SearchTools
from agents import TrendAgent, FinAgent, ReportAgent, IntentAgent
from schema.models import InvestmentSignal, InvestmentReport
from agno.agent import Agent
from utils.md_to_html import save_report_as_html
from prompts.trend_agent import get_news_filter_instructions

os.environ["NO_PROXY"] = "localhost,127.0.0.1,*.hkust-gz.edu.cn"


class SignalFluxWorkflow:
    """
    SignalFlux 主工作流
    
    流程:
    1. TrendAgent -> 扫描热点
    2. FinAgent -> 深度分析 (并行)
    3. ReportAgent -> 生成研报
    """
    
    def __init__(self, db_path: str = "data/signalflux.db"):
        load_dotenv()
        
        # 初始化数据库
        self.db = DatabaseManager(db_path)
        
        # 初始化模型
        provider = os.getenv("LLM_PROVIDER", "ust")
        model_id = os.getenv("LLM_MODEL", "Qwen")
        host = os.getenv("OLLAMA_HOST")
        if host:
            self.model = get_model(provider, model_id, host=host)
        else:
            self.model = get_model(provider, model_id)
        
        # 初始化 Agents
        self.trend_agent = TrendAgent(self.db, self.model, sentiment_mode="bert")
        self.fin_agent = FinAgent(self.db, self.model)
        self.report_agent = ReportAgent(self.db, self.model)
        self.intent_agent = IntentAgent(self.model)
        self.search_tools = SearchTools(self.db)
        
        # 用于筛选的轻量 Agent（不带工具）
        self.filter_agent = Agent(model=self.model, markdown=True, debug_mode=True)
        
        logger.info("🚀 SignalFlux Workflow initialized")
    
    def _llm_filter_signals(self, news_list: List[Dict], depth: Any, query: str = None) -> List[Dict]:
        """使用 LLM 智能筛选高价值信号"""
        if type(depth) == int and len(news_list) <= depth and not query:
            return news_list
        
        # 构建新闻列表文本
        news_text = "\n".join([
            f"[ID: {n.get('id', i)}] {n['title']} (情绪: {n.get('sentiment_score', 'N/A')})"
            for i, n in enumerate(news_list)
        ])
        
        # 生成筛选 prompt (带 query)
        filter_instruction = get_news_filter_instructions(len(news_list), depth, query)
        self.filter_agent.instructions = [filter_instruction]
        
        try:
            response = self.filter_agent.run(f"请筛选以下新闻:\n{news_text}")
            content = response.content
            
            # 提取 JSON
            from utils.json_utils import extract_json
            result = extract_json(content)
            if not result:
                logger.warning(f"Failed to parse LLM filter response: {content}")
                return news_list
            
            selected_ids = result.get("selected_ids", [])
            themes = result.get("themes", [])
            
            logger.info(f"🎯 LLM 筛选结果: {len(selected_ids)} 条, {len(themes)} 个主题")
            
            # 根据 ID 筛选新闻
            id_set = set(str(sid) for sid in selected_ids)
            filtered = [n for n in news_list if str(n.get('id', '')) in id_set]
            
            # 动态逻辑：
            # 1. 只有在 LLM 未选出任何内容且非特定查询时，才回退到默认前几条
            if not filtered and not query:
                 logger.warning("⚠️ LLM selected 0 items, falling back to top items")
                 return news_list
            
            # 2. 如果有 query，完全信任 LLM 的选择（数量可能少于或多于 depth）
            if query:
                return filtered
            
            # 3. 如果是通用扫描，限制最大返回数量
            return filtered
            
        except Exception as e:
            logger.warning(f"⚠️ LLM 筛选失败: {e}, 回退到全部返回")
            return news_list

    # 可用的新闻源（按类别）
    FINANCIAL_SOURCES = ["cls", "wallstreetcn", "xueqiu", "eastmoney", "yicai"]
    SOCIAL_SOURCES = ["weibo", "zhihu", "baidu", "toutiao", "douyin"]
    TECH_SOURCES = ["36kr", "ithome", "v2ex", "juejin", "hackernews"]
    ALL_SOURCES = FINANCIAL_SOURCES + SOCIAL_SOURCES + TECH_SOURCES
    
    def run(self, sources: List[str] = ["all"], wide: int = 10, depth: Any = 'auto', query: Optional[str] = None):
        """执行完整工作流
        
        Args:
            sources: 新闻来源列表
            wide:  新闻抓取广度（每个源抓取的数量）
            depth: 生成报告的深度，若为auto，则由LLM总结判断，若为整数则限制最后生成的信号数量
            query:  用户查询意图（可选），如 "香港火灾"、"A股科技板块"
        """
        logger.info("--- Step 1: Trend Discovery ---")
        
        # 0. 意图分析 (如果存在 query)
        intent_info = ""
        if query:
            logger.info(f"🧠 Analyzing intent for: {query}")
            intent_info = self.intent_agent.run(query)
        
        # 1. 解析 sources 参数
        if "all" in sources:
            actual_sources = self.ALL_SOURCES.copy()
        elif "financial" in sources:
            actual_sources = self.FINANCIAL_SOURCES.copy()
        elif "social" in sources:
            actual_sources = self.SOCIAL_SOURCES.copy()
        elif "tech" in sources:
            actual_sources = self.TECH_SOURCES.copy()
        else:
            actual_sources = sources
        
        logger.info(f"📡 Attempting to fetch from {len(actual_sources)} sources...")
        
        # 2. 获取热点
        successful_sources = []
        for source in actual_sources:
            try:
                # 使用 wide 控制抓取数量
                result = self.trend_agent.news_toolkit.fetch_hot_news(source, count=wide)
                if result and len(result) > 0:
                    successful_sources.append(source)
                else:
                    logger.warning(f"⚠️ Source '{source}' returned no data, skipping")
            except Exception as e:
                logger.warning(f"⚠️ Source '{source}' failed: {e}, skipping")
        
        logger.info(f"✅ Successfully fetched from {len(successful_sources)}/{len(actual_sources)} sources")
            
        # --- NEW: Active Search based on Intent ---
        search_signals = []
        if query and isinstance(intent_info, dict):
            search_queries = intent_info.get("search_queries", [query])
            is_specific = intent_info.get("is_specific_event", False)
            
            # 如果是特定事件，或者用户明确提问，我们应该主动搜索
            if is_specific or len(search_queries) > 0:
                logger.info(f"🔍 Executing active search for queries: {search_queries}")
                for q in search_queries[:2]: # 限制查询数，避免太慢
                    # Consider using 'baidu' for Chinese queries if 'ddg' is unstable
                    # enrich=True is default, so we get full content
                    results = self.search_tools.search_list(q, engine="baidu", max_results=5, enrich=True)
                    for r in results:
                        # 转换为标准信号格式 (search_tools now returns standard keys including id, rank, etc)
                        search_signals.append({
                            "title": r.get('title'),
                            "url": r.get('url'),
                            "source": r.get('source', 'Search'), # keeping original source name
                            "content": r.get('content'),
                            "publish_time": r.get('publish_time') or datetime.now(), 
                            "sentiment_score": r.get('sentiment_score', 0), 
                            "id": r.get('id') or f"search_{hash(r.get('url'))}"
                        })
                logger.info(f"🔍 Found {len(search_signals)} signals via search")

        # 2. 批量更新情绪分数 (保留，用于可视化)
        logger.info("Calculating sentiment scores...")
        self.trend_agent.sentiment_toolkit.batch_update_sentiment(limit=50)
        
        # 3. 从数据库读取新闻 + 合并搜索结果
        db_news = self.db.get_daily_news(limit=50)
        
        # 合并列表 (Search signals preferred if query exists)
        raw_news = search_signals + db_news if search_signals else db_news
        
        if not raw_news:
            logger.warning("No news found in database.")
            return
        
        # 4. 智能筛选（LLM 或传统方式）
        # 如果有 query，即使数量少也建议走 LLM 筛选以匹配相关性
        if depth == 'auto' or query:
            logger.info(f"🤖 Using LLM to filter signals (Query: {query if query else 'Default'})...")
            high_value_signals = self._llm_filter_signals(raw_news, depth, query)
        else:
            # 传统方式：按情绪分数排序
            if type(depth) == int and depth>0:
                high_value_signals = sorted(
                    raw_news, 
                    key=lambda x: abs(x.get("sentiment_score") or 0), 
                    reverse=True
                )[:depth]
            else:
                high_value_signals = raw_news
            
        logger.info(f"--- Step 2: Financial Analysis ({len(high_value_signals)} signals) ---")

        
        analyzed_signals = []
        
        for signal in high_value_signals:
            logger.info(f"Analyzing: {signal['title']}")
            
            # 1. 优先从数据库中寻找同一 signal_id 的深度解析 (ISQ)
            # 这里可以用一个专门的 get_signal 方法，目前我们先看 news 表是否有 analysis 字段缓存（旧逻辑驱动）
            # 或者直接看 signals 表
            
            # 2. 构造上下文
            content = signal.get("content") or ""
            if len(content) < 50 and signal.get("url"):
                content = self.trend_agent.news_toolkit.fetch_news_content(signal["url"]) or ""
            input_text = f"【{signal['title']}】\n{content[:3000]}"
            
            try:
                # 调用 FinAgent 执行 ISQ 解析
                sig_obj = self.fin_agent.analyze_signal(input_text, news_id=signal.get("id"))
                
                if sig_obj:
                    # 补充来源信息 (如果模型没填全)
                    if not sig_obj.sources and signal.get("url"):
                        sig_obj.sources = [{"title": signal["title"], "url": signal["url"], "source_name": signal.get("source", "Unknown")}]
                    
                    # 保存到深度信号表
                    self.db.save_signal(sig_obj.dict())
                    analyzed_signals.append(sig_obj)
                    
                    # 同步回 news 表（旧逻辑兼容）
                    if signal.get("id"):
                        self.db.update_news_content(signal["id"], analysis=sig_obj.summary)
                else:
                    logger.warning(f"Could not get structured analysis for {signal['title']}, skipping")
            except Exception as e:
                logger.error(f"Analysis failed for {signal['title']}: {e}")

        
        logger.info("--- Step 3: Report Generation ---")
        
        result = self.report_agent.generate_report(analyzed_signals, user_query=query)
        # Use a generic name 'report' but note it might be a string now (generate_report returns str)
        report = result
        
        # 保存报告
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        md_filename = f"{report_dir}/daily_report_{timestamp}.md"
        
        with open(md_filename, "w", encoding="utf-8") as f:
            # Handle both RunResponse object and raw string
            md_content = report.content if hasattr(report, "content") else str(report)
            f.write(md_content)
        
        # 转换为 HTML (默认)
        html_filename = save_report_as_html(md_filename)
            
        logger.info(f"✅ Report generated: {md_filename}")
        if html_filename:
            logger.info(f"🌐 HTML Report available: {html_filename}")
            return html_filename
        return md_filename

if __name__ == "__main__":
    workflow = SignalFluxWorkflow()
    workflow.run(query='帮我分析一下近期热点')
    # workflow.run(sources=['social'], wide=5, depth='auto')
