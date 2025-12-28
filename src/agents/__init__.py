# src/agents/__init__.py
"""
SignalFlux Agent 层 - 原生 Agno Agent（需要模型支持 Function Calling）

提供的 Agent 类：
- TrendAgent: 热点趋势发现
- FinAgent: 金融分析师
- ReportAgent: 研报生成器
"""

from agents.trend_agent import TrendAgent
from agents.fin_agent import FinAgent
from agents.report_agent import ReportAgent
from agents.intent_agent import IntentAgent

__all__ = [
    "TrendAgent",
    "FinAgent",
    "ReportAgent",
    "IntentAgent",
]
