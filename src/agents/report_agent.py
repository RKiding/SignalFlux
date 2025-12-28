import json
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict, Any
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from utils.database_manager import DatabaseManager
from utils.hybrid_search import InMemoryRAG
from utils.json_utils import extract_json
from utils.stock_tools import StockTools
import re
from schema.models import InvestmentSignal, InvestmentReport, TransmissionNode
from prompts.report_agent import (
    get_cluster_planner_instructions,
    get_report_planner_instructions,
    get_report_writer_instructions,
    get_report_editor_instructions,
    get_section_editor_instructions,
    get_summary_generator_instructions,
    get_final_assembly_instructions
)


class ReportAgent:
    """
    研报生成器 (ReportAgent) - Map-Reduce 架构
    支持增量编辑模式，避免一次性加载所有章节
    """
    
    def __init__(self, db: DatabaseManager, model: Model, incremental_edit: bool = True):
        self.db = db
        self.model = model
        self.incremental_edit = incremental_edit
        
        # 0. InMemory RAG for cross-chapter context
        self.rag = InMemoryRAG(data=[], text_fields=["title", "content", "summary"])
        
        # 1. Planner Agent
        self.planner = Agent(
            model=model,
            tools=[self.rag.search],
            markdown=True,
            debug_mode=True
        )
        
        # 2. Writer Agent
        self.writer = Agent(
            model=model,
            markdown=True,
            debug_mode=True
        )
        
        # 3. Editor Agent
        self.editor = Agent(
            model=model,
            tools=[self.rag.search],
            markdown=True,
            debug_mode=True
        )
        
        # 5. Section Editor Agent (用于增量编辑)
        self.section_editor = Agent(
            model=model,
            tools=[self.rag.search],
            markdown=True,
            debug_mode=True
        )
        
        logger.info(f"📝 ReportAgent initialized (incremental_edit={incremental_edit})")

    def _format_signal_input(self, signal: Any, index: int) -> str:
        """格式化信号供 prompt 使用 (适配 InvestmentSignal 模型)"""
        # 如果是字典，转为模型
        if isinstance(signal, dict):
            try:
                sig_obj = InvestmentSignal(**signal)
            except:
                # Fallback for old dicts
                return f"--- 信号 [{index}] ---\n标格: {signal.get('title')}\n内容: {signal.get('content', '')[:500]}"
        else:
            sig_obj = signal

        chain_str = " -> ".join([f"{n.node_name}({n.impact_type})" for n in sig_obj.transmission_chain])
        
        text = f"--- 信号 [{index}] ---\n"
        text += f"标题: {sig_obj.title}\n"
        text += f"逻辑摘要: {sig_obj.summary}\n"
        text += f"传导链条: {chain_str}\n"
        text += f"ISQ 评分: 情绪({sig_obj.sentiment_score}), 确定性({sig_obj.confidence}), 强度({sig_obj.intensity})\n"
        text += f"预期博弈: 时窗({sig_obj.expected_horizon}), 预期差({sig_obj.price_in_status})\n"
        
        tickers = ", ".join([f"{t.get('name')}({t.get('ticker')})" for t in sig_obj.impact_tickers])
        if tickers:
            text += f"受影响标的: {tickers}\n"
            
        return text

    def _cluster_signals(self, signals: List[Dict[str, Any]], user_query: str = None) -> List[Dict[str, Any]]:
        """
        使用 Planner 将信号聚类为几个核心主题
        返回: [{"theme_title": "主题A", "signal_ids": [1, 2], "rationale": "..."}]
        """
        # 准备简要输入
        signals_preview = ""
        for i, s in enumerate(signals, 1):
            title = s.title if hasattr(s, 'title') else s.get('title', '')
            signals_preview += f"[{i}] {title}\n"
            
        logger.info(f"🧠 Clustering {len(signals)} signals into themes...")
        
        instruction = get_cluster_planner_instructions(signals_preview, user_query)
        self.planner.instructions = [instruction]
        
        try:
            response = self.planner.run("请对以上信号进行主题聚类。")
            content = response.content
            
            cluster_data = extract_json(content)
            if cluster_data and "clusters" in cluster_data:
                clusters = cluster_data["clusters"]
                logger.info(f"✅ Created {len(clusters)} signal clusters.")
                return clusters
            else:
                logger.warning("⚠️ Failed to parse cluster JSON, fallback to individual signal mode.")
                return []
                
        except Exception as e:
            logger.error(f"Signal clustering failed: {e}")
            return []

    def generate_report(self, signals: List[Dict[str, Any]], user_query: str = None) -> str:
        """
        执行 Write-Plan-Edit 流程生成研报
        """
        stock_tools = StockTools(self.db, auto_update=False)

        logger.info(f"📝 Starting report generation for {len(signals)} signals...")
        
        # --- Phase 1: Signal Clustering ---
        clusters = self._cluster_signals(signals, user_query)
        
        # 如果聚类失败，或者没有返回 clusters，则回退到每个信号一节（模拟每个信号是一个簇）
        if not clusters:
             clusters = [{"theme_title": (s.title if hasattr(s, 'title') else s.get('title', '')), "signal_ids": [i]} for i, s in enumerate(signals, 1)]

        # --- Phase 2: Writing Drafts based on Clusters ---
        sections = []
        sources_list_lines = []
        section_titles = []  # 存储 (anchor, title)
        
        for i, cluster in enumerate(clusters, 1):
            theme_title = cluster.get("theme_title", f"主题 {i}")
            signal_ids = cluster.get("signal_ids", [])
            rationale = cluster.get("rationale", "")
            
            logger.info(f"✍️ Writing draft for theme [{i}/{len(clusters)}]: {theme_title} (Signals: {signal_ids})...")
            
            # 聚合该簇下的所有信号内容
            cluster_signals_text = ""
            cluster_price_context = ""
            cluster_tickers_seen = set()
            
            for sig_idx in signal_ids:
                # 注意：signal_ids 是 1-based，访问 list 需要 -1
                if sig_idx < 1 or sig_idx > len(signals):
                    continue
                    
                signal = signals[sig_idx-1]
                
                # 收集 Sources
                if hasattr(signal, 'sources'):
                    for src in signal.sources:
                        sources_list_lines.append(f"[{sig_idx}] {src.get('title')} ({src.get('source_name')}), {src.get('url', 'N/A')}")
                elif isinstance(signal, dict) and 'source' in signal:
                    sources_list_lines.append(f"[{sig_idx}] {signal.get('title')} ({signal.get('source')}), {signal.get('url', 'N/A')}")
                
                # 聚合信号文本
                cluster_signals_text += self._format_signal_input(signal, sig_idx) + "\n"
                
                # 聚合行情 Context (去重)
                analysis_text = getattr(signal, 'analysis', '') if not isinstance(signal, dict) else signal.get('analysis', '')
                potential_tickers = list(set(re.findall(r'\b(\d{6})\b', analysis_text)))
                for t in potential_tickers:
                    if t not in cluster_tickers_seen:
                        cluster_tickers_seen.add(t)
                        # 获取行情
                        try:
                            end_date = datetime.now().strftime("%Y-%m-%d")
                            start_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
                            df_ctx = stock_tools.get_stock_price(t, start_date=start_date, end_date=end_date)
                            if not df_ctx.empty:
                                last_5 = df_ctx.tail(5)
                                prices_str = ", ".join([f"{row['date']}:{row['close']}" for _, row in last_5.iterrows()])
                                cluster_price_context += f"- {t}: {prices_str}\n"
                        except:
                            continue

            # 撰写单节草稿 (基于主题)
            writer_instruction = get_report_writer_instructions(
                theme_title=theme_title,
                signal_cluster_text=cluster_signals_text,
                signal_indices=signal_ids,
                price_context=cluster_price_context,
                user_query=user_query
            )
            
            try:
                self.writer.instructions = [writer_instruction] 
                response = self.writer.run(f"请依据主题 '{theme_title}' 和 输入信号集 开始撰写。")
                content = response.content.strip()
                
                # 尝试提取第一行作为标题
                lines = content.split('\n')
                title_line = lines[0].strip().replace('###', '').strip().replace('#', '')
                # 如果第一行太长或者没标题，就用 theme_title
                final_title = title_line if title_line and len(title_line) < 50 else theme_title
                
                # 存储原始章节，带锚点
                section_content = f"<a id=\"section-{i}\"></a>\n\n{content}\n"
                sections.append(section_content)
                section_titles.append((f"section-{i}", final_title))
                
            except Exception as e:
                logger.error(f"Failed to write section for theme {theme_title}: {e}")
        
        if not sections:
            return "⚠️ 无法生成研报：没有有效的分析章节。"

        sources_list_text = "\n".join(sources_list_lines)
        
        # --- Decision Point: Incremental vs Global ---
        # 如果开启增量编辑，或者内容总长度超过阈值（如 80000 字符），使用增量模式以避免上下文溢出
        total_content_length = sum(len(s) for s in sections)
        use_incremental = self.incremental_edit or total_content_length > 80000
        
        if use_incremental:
            logger.info(f"🔄 Using INCREMENTAL editing mode (sections={len(sections)})...")
            final_response_content = self._incremental_edit(sections, sources_list_text, section_titles)
        else:
            # --- Phase 3: Global Planning (The Planner) ---
            # 虽然已经聚类，但全局 Planner 仍有助于调整章节顺序和识别分歧
            logger.info("🧠 Using GLOBAL Planning & Editing mode...")
            
            # ... (Rest of global logic remains mostly the same, just operating on theme sections)
            draft_docs = []
            toc_lines = []
            for i, section in enumerate(sections, 1):
                title = section_titles[i-1][1]
                draft_docs.append({
                    "id": str(i),
                    "title": title,
                    "content": section,
                    "summary": section[:500]
                })
                toc_lines.append(f"[{i}] {title}")
            
            self.rag.update_data(draft_docs)
            toc_text = "\n".join(toc_lines)
            
            planner_instruction = get_report_planner_instructions(toc_text, len(signals), user_query)
            self.planner.instructions = [planner_instruction]
            
            try:
                plan_response = self.planner.run("请阅读现有草稿并规划终稿大纲。")
                report_plan = plan_response.content
                logger.info("✅ Report plan generated.")
            except Exception as e:
                logger.error(f"Planning failed: {e}")
                report_plan = "（规划失败，请按默认顺序编排）"

            # --- Phase 4: Final Editing (The Editor) ---
            logger.info("🎬 Editing final report based on plan...")
            
            all_drafts_text = "\n---\n".join(sections)
            editor_instruction = get_report_editor_instructions(all_drafts_text, report_plan, sources_list_text)
            self.editor.instructions = [editor_instruction]
            
            try:
                # 使用 Editor 进行重组和润色
                final_response = self.editor.run("请根据规划大纲和草稿内容，生成最终研报。")
                final_response_content = final_response.content
            except Exception as e:
                logger.error(f"Final editing failed: {e}")
                final_response_content = f"# 研报生成失败\n\n{e}"

        # 清理 Markdown 标记
        final_response_content = final_response_content.strip()
        if final_response_content.startswith("```markdown"):
            final_response_content = final_response_content[len("```markdown"):].strip()
        if final_response_content.startswith("```"):
            final_response_content = final_response_content[3:].strip()
        if final_response_content.endswith("```"):
            final_response_content = final_response_content[:-3].strip()

        # 统一添加 TOC (如果 Editor 未生成)
        if not use_incremental and "[TOC]" not in final_response_content:
             lines = final_response_content.split('\n')
             if lines and lines[0].strip().startswith('# '):
                 # 插入在标题之后
                 final_response_content = lines[0] + "\n\n[TOC]\n\n" + "\n".join(lines[1:])
             else:
                 # 插入在最前
                 final_response_content = "[TOC]\n\n" + final_response_content
        
        # Fix duplicate headers (e.g. "#### #### Title") caused by LLM stutter
        final_response_content = re.sub(r'(#{1,6})\s+\1', r'\1', final_response_content)
        
        # --- Phase 5: Visualization Processing ---
        logger.info("🎨 Processing visualization...")
        final_report_with_charts = self._process_charts(final_response_content)
        
        return final_report_with_charts

    def _clean_markdown(self, text: str) -> str:
        """Helper to remove markdown code fences"""
        text = text.strip()
        if text.startswith("```markdown"):
            text = text[len("```markdown"):].strip()
        elif text.startswith("```"):
            text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        return text

    def _incremental_edit(self, sections: List[str], sources_list_text: str, section_titles_data: List[tuple] = None) -> str:
        """增量编辑模式"""
        import time
        
        # 1. 填充 RAG
        draft_docs = []
        toc_lines = []
        for i, section in enumerate(sections, 1):
            if section_titles_data and i <= len(section_titles_data):
                _, title = section_titles_data[i-1]
            else:
                title = f"章节 {i}"
            
            draft_docs.append({
                "id": str(i),
                "title": title,
                "content": section,
                "summary": section[:300]
            })
            toc_lines.append(f"[{i}] {title}")
        
        self.rag.update_data(draft_docs)
        toc = "\n".join(toc_lines)
        
        # 2. 逐节编辑
        edited_sections = []
        for i, section in enumerate(sections, 1):
            logger.info(f"✍️ Incremental editing: section {i}/{len(sections)}...")
            
            editor_instruction = get_section_editor_instructions(i, len(sections), toc)
            self.section_editor.instructions = [editor_instruction]
            
            try:
                response = self.section_editor.run(f"请编辑以下章节内容：\n\n{section}")
                cleaned_content = self._clean_markdown(response.content)
                edited_sections.append(cleaned_content)
            except Exception as e:
                logger.warning(f"⚠️ Section {i} editing failed: {e}, using original")
                edited_sections.append(self._clean_markdown(section))
            
            # 简短延迟避免 API 过载
            time.sleep(0.5)
        
        # 3. 生成摘要
        logger.info("📝 Generating summary (incremental)...")
        section_summaries = "\n".join([s[:200] + "..." for s in edited_sections])
        summary_instruction = get_summary_generator_instructions(toc, section_summaries)
        self.editor.instructions = [summary_instruction]
        
        try:
            summary_response = self.editor.run("请生成核心观点摘要。")
            summary = self._clean_markdown(summary_response.content)
        except Exception as e:
            logger.warning(f"⚠️ Summary generation failed: {e}")
            summary = "（摘要生成失败，请参阅各章节详情。）"
        
        # 4. 生成参考文献和尾部内容
        logger.info("📚 Generating references (incremental)...")
        assembly_instruction = get_final_assembly_instructions(sources_list_text)
        self.editor.instructions = [assembly_instruction]
        
        try:
            tail_response = self.editor.run("请生成参考文献、风险提示和快速扫描表格。")
            tail_content = self._clean_markdown(tail_response.content)
            
            # 分离快速扫描和其他尾部内容
            quick_scan = ""
            other_tail = tail_content
            if "快速扫描" in tail_content:
                parts = tail_content.split("## 快速扫描")
                if len(parts) == 2:
                    other_tail = parts[0].strip()
                    quick_scan = "## 快速扫描" + parts[1].split("## ")[0] if "## " in parts[1] else "## 快速扫描" + parts[1]
        except Exception as e:
            logger.warning(f"⚠️ Tail content generation failed: {e}")
            quick_scan = ""
            other_tail = f"""## 参考文献

            {sources_list_text}

            ## 风险提示

            本报告由 AI 自动生成，仅供参考，不构成投资建议。
            """
        
        # 5. 组装最终报告
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        import textwrap
        import re
        
        # 清理 edited_sections：只做代码块保护和基本清理
        
        # 清理 edited_sections 中的标题层级问题
        cleaned_sections = []
        for section in edited_sections:
            # 保护代码块：先临时替换代码块内容
            code_blocks = []
            def preserve_code_block(match):
                code_blocks.append(match.group(0))
                return f"__CODE_BLOCK_{len(code_blocks) - 1}__"
            
            section_protected = re.sub(r'```[\s\S]*?```', preserve_code_block, section)
            
            # 只清理明显的错误：重复的 # 符号（LLM stutter）
            # 移除重复的 # 符号
            section_fixed = re.sub(r'(#{1,6})\s+\1+', r'\1', section_protected)
            
            # 恢复代码块
            for i, block in enumerate(code_blocks):
                section_fixed = section_fixed.replace(f"__CODE_BLOCK_{i}__", block)
            
            cleaned_sections.append(section_fixed)
        
        # Use simple string concatenation or 0-indented string to avoid dedent issues with dynamic content
        final_report = f"""# SignalFlux 全球市场趋势日报 ({current_date})

[TOC]

{quick_scan}

## 核心观点摘要

{summary}

{"\n\n".join(cleaned_sections)}

{other_tail}
"""
        # Fix duplicate headers (e.g. "#### #### Title") caused by LLM stutter
        final_report = re.sub(r'(#{1,6})\s+\1', r'\1', final_report)
        
        # 移除连续的空行（最多保留2个）
        final_report = re.sub(r'\n{4,}', '\n\n\n', final_report)
         
        return final_report.strip()
    

    def _process_charts(self, content: str) -> str:
        """解析 json-chart 代码块并替换为 HTML 链接/Iframe"""

        import re
        from utils.visualizer import VisualizerTools
        from utils.stock_tools import StockTools
        
        stock_tools = StockTools(self.db, auto_update=False)

        def replace_match(match):
            from utils.json_utils import extract_json
            json_str = match.group(1).strip()
            try:
                config = extract_json(json_str)
                if not config:
                    raise ValueError("No valid JSON found in chart block")
                
                chart_type = config.get("type")
                
                if chart_type == "stock":
                    ticker_raw = config.get("ticker", "")
                    base_title = config.get("title", f"{ticker_raw} 走势")
                    prediction = config.get("prediction", None)
                    
                    # 处理多个 ticker 的情况（逗号或空格分隔）
                    tickers = re.split(r'[,\s]+', str(ticker_raw).strip())
                    
                    # 尝试解析每个 ticker
                    valid_tickers = []
                    for t in tickers:
                        t = t.strip()
                        if not t:
                            continue
                        
                        # 标准6位数字格式
                        if len(t) == 6 and t.isdigit():
                            valid_tickers.append(t)
                        # 带后缀格式：301367.SZ, 600519.SH
                        elif '.' in t:
                            code_part = t.split('.')[0]
                            if len(code_part) == 6 and code_part.isdigit():
                                valid_tickers.append(code_part)
                                logger.info(f"📊 Extracted ticker {code_part} from {t}")
                        # 尝试模糊匹配（用公司名搜索）
                        elif len(t) > 1:
                            try:
                                search_results = stock_tools.search_ticker(t)
                                if search_results and len(search_results) > 0:
                                    first_match = search_results[0].get('code', '')
                                    if first_match:
                                        valid_tickers.append(first_match)
                                        logger.info(f"📊 Fuzzy matched ticker {first_match} from query '{t}'")
                            except Exception as e:
                                logger.warning(f"⚠️ Fuzzy search failed for {t}: {e}")
                    
                    tickers = valid_tickers
                    
                    if not tickers:
                        logger.warning(f"⚠️ No valid ticker found in: {ticker_raw}")
                        return f"\n<!-- 无法解析股票代码: {ticker_raw} -->\n"

                    
                    if len(tickers) > 1:
                        logger.info(f"📊 Multiple tickers detected: {tickers}, generating charts for all")
                    
                    # 为每个 ticker 生成图表
                    all_charts_html = []
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
                    
                    for idx, ticker in enumerate(tickers):
                        # 如果有多个 ticker，为每个生成独立的标题
                        if len(tickers) > 1:
                            chart_title = f"{ticker} - {base_title}"
                        else:
                            chart_title = base_title
                        
                        df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date)
                        
                        if not df.empty:
                            # 如果有 prediction 且是多个 ticker，尝试分配预测值
                            ticker_prediction = None
                            if prediction and isinstance(prediction, list):
                                # 假设预测值平均分配给每个 ticker
                                chunk_size = len(prediction) // len(tickers) if len(tickers) > 1 else len(prediction)
                                if chunk_size > 0:
                                    start_idx = idx * chunk_size
                                    end_idx = start_idx + chunk_size
                                    ticker_prediction = prediction[start_idx:end_idx] if end_idx <= len(prediction) else prediction[start_idx:]
                                if not ticker_prediction:
                                    ticker_prediction = prediction[:3] if len(prediction) >= 3 else prediction
                            
                            chart = VisualizerTools.generate_stock_chart(df, ticker, chart_title, ticker_prediction)
                            if chart:
                                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                filename = f"reports/charts/{ticker}_{timestamp}.html"
                                VisualizerTools.render_chart_to_file(chart, filename)
                                
                                rel_path = f"charts/{ticker}_{timestamp}.html"
                                all_charts_html.append(
                                    f'<iframe src="{rel_path}" width="100%" height="500px" style="border:none;"></iframe>\n'
                                    f'<p style="text-align:center;color:gray;font-size:12px">交互式图表: {chart_title}</p>'
                                )
                        else:
                            logger.warning(f"⚠️ No data for ticker: {ticker}")
                    
                    if all_charts_html:
                        return "\n" + "\n".join(all_charts_html) + "\n"
                    else:
                        return f"\n<!-- 无法获取股票数据: {ticker_raw} -->\n"


                
                elif chart_type == "sentiment":
                    keywords = config.get("keywords", [])
                    title = config.get("title", "舆情情绪趋势")
                    
                    if keywords:
                        # 简单的 SQL 查询 (注意可能有 SQL 注入风险，但在 Agent 内部可控)
                        # 构造 OR 查询以获取更多相关数据
                        conditions = " OR ".join([f"content LIKE '%{k}%'" for k in keywords])
                        query = f"SELECT publish_time, sentiment_score FROM daily_news WHERE ({conditions}) AND sentiment_score IS NOT NULL ORDER BY publish_time"
                        
                        logger.info(f"📊 Executing sentiment query: {query}")
                        results = self.db.execute_query(query)
                        logger.info(f"📊 Query result count: {len(results)}")
                        
                        if not results or len(results) == 0:
                            # Fallback: Try broadening search by splitting keywords
                            logger.info("⚠️ Initial sentiment query empty, attempting fallback with split keywords...")
                            broad_keywords = []
                            for k in keywords:
                                broad_keywords.extend(k.split())
                            
                            # Deduplicate and filter short words
                            broad_keywords = list(set([k for k in broad_keywords if len(k) > 1]))
                            
                            if broad_keywords:
                                conditions = " OR ".join([f"content LIKE '%{k}%'" for k in broad_keywords])
                                query = f"SELECT publish_time, sentiment_score FROM daily_news WHERE ({conditions}) AND sentiment_score IS NOT NULL ORDER BY publish_time"
                                logger.info(f"📊 Executing fallback sentiment query: {query}")
                                results = self.db.execute_query(query)
                                logger.info(f"📊 Fallback query result count: {len(results)}")

                        if results:
                            # 格式化数据
                            sentiment_history = []
                            for row in results:
                                try:
                                    # 假设 publish_time 是字符串，或者 date object
                                    dt = row[0]
                                    if isinstance(dt, datetime):
                                        d_str = dt.strftime("%Y-%m-%d")
                                    else:
                                        d_str = str(dt)[:10] # 截取日期部分
                                        
                                    sentiment_history.append({"date": d_str, "score": row[1]})
                                except:
                                    continue
                            
                            # 聚合每天的平均分
                            df_sent = pd.DataFrame(sentiment_history)
                            if not df_sent.empty:
                                df_sent = df_sent.groupby('date')['score'].mean().reset_index()
                                sentiment_history_agg = df_sent.to_dict('records')
                                
                                chart = VisualizerTools.generate_sentiment_trend_chart(sentiment_history_agg)
                                if chart:
                                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                                    filename = f"reports/charts/sentiment_{timestamp}.html"
                                    VisualizerTools.render_chart_to_file(chart, filename)
                                    rel_path = f"charts/sentiment_{timestamp}.html"
                                    return f'\n<iframe src="{rel_path}" width="100%" height="400px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">交互式图表: {title}</p>\n'
                        
                        # Fallback for sentiment if query results are empty
                        return f'\n<p style="text-align:center;color:gray;font-size:12px;padding:20px;border:1px dashed #ccc;border-radius:8px;">📊 暂无足够历史数据生成 "{title}" 的趋势图</p>\n'

                elif chart_type == "isq":
                    sentiment = config.get("sentiment", 0.0)
                    confidence = config.get("confidence", 0.5)
                    intensity = config.get("intensity", 3)
                    expectation_gap = config.get("expectation_gap", 0.5)
                    timeliness = config.get("timeliness", 0.8)
                    title = config.get("title", "信号质量 ISQ 评估")
                    
                    chart = VisualizerTools.generate_isq_radar_chart(
                        sentiment, confidence, intensity, 
                        expectation_gap=expectation_gap, 
                        timeliness=timeliness, 
                        title=title
                    )
                    if chart:
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        filename = f"reports/charts/isq_{timestamp}.html"
                        VisualizerTools.render_chart_to_file(chart, filename)
                        rel_path = f"charts/isq_{timestamp}.html"
                        return f'\n<iframe src="{rel_path}" width="100%" height="420px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">信号质量雷达图: {title}</p>\n'

                elif chart_type == "transmission":
                    nodes = config.get("nodes", [])
                    title = config.get("title", "投资逻辑传导链条")
                    
                    if nodes:
                        # 生成基于节点内容的唯一标识，避免相同时间戳下的重复图表
                        import hashlib
                        nodes_str = json.dumps(nodes, sort_keys=True, ensure_ascii=False)
                        content_hash = hashlib.md5(nodes_str.encode()).hexdigest()[:8]
                        
                        chart = VisualizerTools.generate_transmission_graph(nodes, title)
                        if chart:
                            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                            filename = f"reports/charts/trans_{timestamp}_{content_hash}.html"
                            VisualizerTools.render_chart_to_file(chart, filename)
                            rel_path = f"charts/trans_{timestamp}_{content_hash}.html"
                            return f'\n<iframe src="{rel_path}" width="100%" height="420px" style="border:none;"></iframe>\n<p style="text-align:center;color:gray;font-size:12px">逻辑传导拓扑图: {title}</p>\n'

                # 如果是其他类型或失败，保留原文或者显示错误
                return f"```json\n{json_str}\n```" # Fallback to json display if render fails logic mismatch
            
            except Exception as e:
                logger.error(f"Chart processing failed: {e}")
                return match.group(0) # Return original text on error

        # 匹配 ```json-chart ... ```
        pattern = re.compile(r'```json-chart\s*(\{.*?\})\s*```', re.DOTALL)
        new_content = pattern.sub(replace_match, content)
        
        return new_content
