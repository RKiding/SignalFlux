from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class TransmissionNode(BaseModel):
    node_name: str = Field(..., description="产业链节点名称")
    impact_type: str = Field(..., description="利好/利空/中性")
    logic: str = Field(..., description="该节点的传导逻辑")

class IntentAnalysis(BaseModel):
    keywords: List[str] = Field(..., description="核心实体、事件或概念关键词")
    search_queries: List[str] = Field(..., description="优化后的搜索引擎查询词")
    is_specific_event: bool = Field(..., description="是否查询特定突发事件")
    time_range: str = Field(..., description="时间范围 (recent/all/specific_date)")
    intent_summary: str = Field(..., description="一句话意图描述")

class InvestmentSignal(BaseModel):
    # 核心元数据
    signal_id: str = Field(default="unknown_sig", description="唯一信号 ID")
    title: str = Field(default="未命名信号", description="信号标题")
    summary: str = Field(default="暂无摘要分析", description="100 字核心观点快报")
    
    # 逻辑传导 (ISQ Key 1)
    transmission_chain: List[TransmissionNode] = Field(default_factory=list, description="产业链传导逻辑链条")
    
    # 信号质量 (ISQ Key 2)
    sentiment_score: float = Field(default=0.0, description="基础情绪偏向 (-1.0 到 1.0)")
    confidence: float = Field(default=0.5, description="信号确定性分值 (0.0 到 1.0)")
    intensity: int = Field(default=3, description="信号强度等级 (1-5)")
    expectation_gap: float = Field(default=0.5, description="预期差/博弈空间 (0.0 到 1.0)")
    timeliness: float = Field(default=0.8, description="时效性/窗口紧迫度 (0.0 到 1.0)")
    
    # 预测与博弈 (ISQ Key 3)
    expected_horizon: str = Field(default="T+N", description="预期的反应时窗 (如: T+0, T+3, Long-term)")
    price_in_status: str = Field(default="未知", description="市场预期消化程度 (未定价/部分定价/充分定价)")
    
    # 关联实体
    impact_tickers: List[Dict[str, Any]] = Field(default_factory=list, description="受影响的代码列表及其权重")
    industry_tags: List[str] = Field(default_factory=list, description="关联行业标签")
    
    # 溯源
    sources: List[Dict[str, str]] = Field(default_factory=list, description="来源详情 (包含 title, url, source_name)")
    
class InvestmentReport(BaseModel):
    overall_sentiment: str = Field(..., description="整体市场情绪评价")
    market_entropy: float = Field(..., description="市场分歧度 (0-1, 1代表极高分歧)")
    signals: List[InvestmentSignal] = Field(..., description="深度解析的投资信号列表")
    timestamp: str = Field(..., description="报告生成时间")
    meta_info: Optional[Dict[str, Any]] = Field(default_factory=dict, description="其他元数据")
