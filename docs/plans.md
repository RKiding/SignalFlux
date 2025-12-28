几个重要的修改方向：
1. sentiment的可视化需要完善，比如部分需要横向比较的可能用饼图，需要时序、面板的用折线图等；关键词查询的精细度可能可以提高；sentiment的输出也可以优化（支持多种model）

目前版本的一个样例：2025-12-27 22:12:39.386 | INFO     | agents.report_agent:replace_match:475 - 📊 Executing sentiment query: SELECT publish_time, sentiment_score FROM daily_news WHERE (content LIKE '%商业火箭%' OR content LIKE '%科创板%' OR content LIKE '%发射载荷%' OR content LIKE '%卫星组网%' OR content LIKE '%产业链整合%') AND sentiment_score IS NOT NULL ORDER BY publish_time

2. AI的预测可以结合时序模型的预测结果（可以获取特定步长的预测，在其结果上微调），比如使用Kronos（https://github.com/shiyu-coder/Kronos）

3. 新闻的召回一方面可以增加API的来源（已经写好的polymarket tool还没有接入），另一方面可以引入搜索、推荐算法的一些架构，从召回、粗排、精排、（多样性）等步骤来优化召回的效果

4. 待定：ReAct模式或者LangGraph等框架的引入；更多股票API的引入（以支持美股等标的）