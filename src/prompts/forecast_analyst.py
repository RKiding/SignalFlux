from typing import List, Dict, Any
from schema.models import KLinePoint

def get_forecast_adjustment_instructions(ticker: str, news_context: str, model_forecast: List[KLinePoint]):
    """
    生成 LLM 预测调整指令
    """
    forecast_str = "\n".join([f"- {p.date}: O:{p.open}, C:{p.close}" for p in model_forecast])
    
    return f"""你是一位资深的量化策略分析师。
你的任务是：根据给定的【Kronos 模型预测结果】和【最新的基本面/新闻背景】，对模型预测进行“主观/逻辑调整”。

股票代码: {ticker}

【Kronos 模型原始预测 (OHLC)】:
{forecast_str}

【最新情报背景】:
{news_context}

调整原则:
1. Kronos 模型是基于历史趋势的时序模型，不具备捕捉突发新闻或重大政策变动的功能。
2. 你需要评估新闻信号（利多/利空）是否会打破当前趋势。
3. 如果新闻非常重磅，建议调整对应日期的 Close 和 High/Low 值。
4. 如果新闻影响有限，可保持或小幅修正。

输出要求 (严格 JSON 格式):
```json
{{
  "adjusted_forecast": [
    {{
      "date": "YYYY-MM-DD",
      "open": float,
      "high": float,
      "low": float,
      "close": float,
      "volume": float
    }},
    ...
  ],
  "rationale": "详细说明调整的逻辑依据，例如：考虑到[事件A]，预期短线将突破压力位..."
}}
```
注意：必须输出与原始预测相同数量的数据点，且日期一一对应。
"""

def get_forecast_task():
    return "请根据以上背景和模型预测，给出调整后的 K 线数据并说明理由。"
