import os
import hashlib
import json
import re
from typing import List, Dict, Optional, Any
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.baidusearch import BaiduSearchTools
from agno.agent import Agent
from loguru import logger
from datetime import datetime
from utils.database_manager import DatabaseManager
from utils.content_extractor import ContentExtractor
from utils.llm.factory import get_model
from utils.hybrid_search import LocalNewsSearch

# 默认搜索缓存 TTL（秒），可通过环境变量覆盖
DEFAULT_SEARCH_TTL = int(os.getenv("SEARCH_CACHE_TTL", "3600"))  # 默认 1 小时

class SearchTools:
    """扩展性搜索工具库 - 支持多引擎聚合与内容缓存"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self._engines = {
            "ddg": DuckDuckGoTools(),
            "baidu": BaiduSearchTools(),
            "local": LocalNewsSearch(db)
        }

    def _generate_hash(self, query: str, engine: str, max_results: int) -> str:
        return hashlib.md5(f"{engine}:{query}:{max_results}".encode()).hexdigest()

    def search(self, query: str, engine: str = "ddg", max_results: int = 5, ttl: Optional[int] = None) -> str:
        """
        使用指定搜索引擎执行网络搜索，结果会被缓存以提高效率。
        
        Args:
            query: 搜索关键词，如 "英伟达财报" 或 "光伏行业政策"。
            engine: 搜索引擎选择。可选值: "ddg" (DuckDuckGo，推荐英文/国际搜索), 
                    "baidu" (百度，推荐中文/国内搜索),
                    "local" (本地历史新闻搜索，基于向量+BM25)。默认 "ddg"。
            max_results: 期望返回的结果数量，默认 5 条。
            ttl: 缓存有效期（秒）。如果缓存超过此时间会重新搜索。
                 默认使用环境变量 SEARCH_CACHE_TTL 或 3600 秒。
                 设为 0 可强制刷新。
        
        Returns:
            搜索结果的文本描述，包含标题、摘要和链接。
        """
        if engine not in self._engines:
            return f"Error: Unsupported engine '{engine}'. Available: {list(self._engines.keys())}"

        query_hash = self._generate_hash(query, engine, max_results)
        effective_ttl = ttl if ttl is not None else DEFAULT_SEARCH_TTL
        
        # 1. 尝试从缓存读取 (local 引擎不缓存，因为它本身就是查库)
        if engine != "local":
            cache = self.db.get_search_cache(query_hash, ttl_seconds=effective_ttl if effective_ttl > 0 else None)
            if cache and effective_ttl != 0:
                logger.info(f"ℹ️ Found search results in cache for: {query} ({engine})")
                return cache['results']

        # 2. 执行真实搜索
        logger.info(f"📡 Searching {engine} for: {query}")
        try:
            tool = self._engines[engine]
            if engine == "ddg":
                results = tool.duckduckgo_search(query, max_results=max_results)
            elif engine == "baidu":
                results = tool.baidu_search(query, max_results=max_results)
            elif engine == "local":
                # LocalNewsSearch 返回的是 List[Dict]
                local_results = tool.search(query, top_n=max_results)
                results = []
                for r in local_results:
                    results.append({
                        "title": r.get("title"),
                        "href": r.get("url", "local"),
                        "body": r.get("content", "")[:300]
                    })
            else:
                results = "Search not implemented for this engine."
            
            results_str = str(results)
            if engine != "local":
                self.db.save_search_cache(query_hash, query, engine, results_str)
            return results_str
            
        except Exception as e:
            logger.error(f"❌ Search failed for {query}: {e}")
            return f"Error occurred during search: {str(e)}"

    def search_list(self, query: str, engine: str = "ddg", max_results: int = 5, ttl: Optional[int] = None, enrich: bool = True) -> List[Dict]:
        """
        执行搜索并返回结构化列表 (List[Dict])。
        Dict 包含: title, href (or url), body (or snippet)
        
        Args:
            enrich: 是否抓取正文内容 (默认 True)
        """
        if engine not in self._engines:
            logger.error(f"Unsupported engine {engine}")
            return []
            
        # 不同的 hash 以区分是否 enrichment
        enrich_suffix = ":enriched" if enrich else ""
        query_hash = self._generate_hash(query, engine + enrich_suffix, max_results)
        effective_ttl = ttl if ttl is not None else DEFAULT_SEARCH_TTL
        
        # 1. 尝试从缓存读取
        cache = self.db.get_search_cache(query_hash, ttl_seconds=effective_ttl if effective_ttl > 0 else None)
        if cache and effective_ttl != 0:
            try:
                cached_data = json.loads(cache['results'])
                if isinstance(cached_data, list):
                    logger.info(f"ℹ️ Found structured search cache for: {query}")
                    return cached_data
            except:
                pass
        
        # 1.5 Smart Cache (Fuzzy + LLM)
        if effective_ttl != 0:
            try:
                # 1. Similar cached queries
                similar_queries = self.db.find_similar_queries(query, limit=3)
                # Filter by TTL
                valid_candidates = []
                for q in similar_queries:
                    if q['query'] == query: continue 
                    q_time = datetime.fromisoformat(q['timestamp'])
                    if effective_ttl and (datetime.now() - q_time).total_seconds() > effective_ttl:
                        continue
                    q['type'] = 'cached_search'
                    valid_candidates.append(q)

                # 2. Relevant local news (as search results)
                local_news = self.db.search_local_news(query, limit=3)
                if local_news:
                    # Group local news as a single "candidate" source? Or individual?
                    # Better to treat "Local News Database" as one candidate source that contains X items.
                    # Or just add them to candidates list?
                    # Let's package strictly relevant news as a "local_news_bundle"
                    valid_candidates.append({
                        'type': 'local_news',
                        'query': 'Local Database News',
                        'items': local_news,
                        'timestamp': datetime.now().isoformat()
                    })
                
                if valid_candidates:
                    logger.info(f"🤔 Found {len(valid_candidates)} smart cache candidates (Queries/News). Asking LLM...")
                    evaluation = self._evaluate_cache_relevance(query, valid_candidates)
                    
                    if evaluation and evaluation.get('reuse', False):
                        idx = evaluation.get('index', -1)
                        if 0 <= idx < len(valid_candidates):
                            chosen = valid_candidates[idx]
                            logger.info(f"🤖 LLM suggested reusing: '{chosen.get('query')}' ({chosen['type']})")
                            
                            if chosen['type'] == 'cached_search':
                                # Load the chosen cache
                                cache = self.db.get_search_cache(chosen['query_hash']) 
                                if cache:
                                    try:
                                        cached_data = json.loads(cache['results'])
                                        if isinstance(cached_data, list):
                                            return cached_data
                                    except:
                                        pass
                            elif chosen['type'] == 'local_news':
                                # Convert local news items to search result format
                                news_results = []
                                for i, news in enumerate(chosen['items'], 1):
                                    news_results.append({
                                        "id": news.get('id'),
                                        "rank": i,
                                        "title": news.get('title'),
                                        "url": news.get('url'),
                                        "content": news.get('content'),
                                        "original_snippet": news.get('content')[:200] if news.get('content') else '',
                                        "source": f"Local News ({news.get('source')})",
                                        "publish_time": news.get('publish_time'),
                                        "crawl_time": news.get('crawl_time'),
                                        "sentiment_score": news.get('sentiment_score', 0),
                                        "meta_data": {"origin": "local_db"}
                                    })
                                return news_results

            except Exception as e:
                logger.warning(f"Smart cache check failed: {e}")
        
        # 2. 执行搜索
        logger.info(f"📡 Searching {engine} (structured) for: {query}")
        try:
            tool = self._engines[engine]
            results = []
            if engine == "ddg":
                results = tool.duckduckgo_search(query, max_results=max_results)
            elif engine == "baidu":
                results = tool.baidu_search(query, max_results=max_results)
            elif engine == "local":
                # LocalNewsSearch 返回的是 List[Dict]
                local_results = tool.search(query, top_n=max_results)
                results = []
                for r in local_results:
                    results.append({
                        "title": r.get("title"),
                        "url": r.get("url", "local"),
                        "body": r.get("content", "")[:500],
                        "source": f"Local ({r.get('source', 'db')})",
                        "publish_time": r.get("publish_time")
                    })
            
            # 处理字符串类型的 JSON 返回 (Baidu 常返 JSON 字符串)
            if isinstance(results, str) and engine != "local":
                try:
                    results = json.loads(results)
                except:
                    pass
            
            # 转为统一格式
            normalized_results = []
            if isinstance(results, list):
                
                for i, r in enumerate(results, 1):
                    title = r.get('title', '')
                    url = r.get('href') or r.get('url') or r.get('link', '')
                    content = r.get('body') or r.get('snippet') or r.get('abstract', '')
                    
                    if title and url:
                        normalized_results.append({
                            "id": self._generate_hash(url + query, "search_item", i),
                            "rank": i,
                            "title": title,
                            "url": url,
                            "content": content,
                            "original_snippet": content, # 保留摘要
                            "source": f"Search ({engine})",
                            "publish_time": datetime.now().isoformat(), # 暂用当前时间
                            "crawl_time": datetime.now().isoformat(),
                            "meta_data": {"query": query, "engine": engine}
                        })
            
            # Fallback if still string and failed to parse
            elif isinstance(results, str) and results:
                 normalized_results.append({"title": query, "url": "", "content": results, "source": engine})

            # 3. 抓取正文 & 计算情绪 (Enrichment)
            if enrich and normalized_results:
                logger.info(f"🕸️ Enriching {len(normalized_results)} search results with Jina & Sentiment...")
                extractor = ContentExtractor()
                
                # Lazy load sentiment tool
                if not hasattr(self, 'sentiment_tool') or self.sentiment_tool is None:
                    from utils.sentiment_tools import SentimentTools
                    self.sentiment_tool = SentimentTools(self.db)
                
                for item in normalized_results:
                    if item.get("url"):
                        try:
                            # Use Jina to get full content
                            full_content = extractor.extract_with_jina(item["url"], timeout=60)
                            if full_content and len(full_content) > 100:
                                item["content"] = full_content
                                
                                # Calculate sentiment
                                # Use title + snippet of content for efficiency
                                text_to_analyze = f"{item['title']} {full_content[:500]}"
                                sent_result = self.sentiment_tool.analyze_sentiment(text_to_analyze)  # Using self.sentiment_tool
                                score = sent_result.get('score', 0.0)
                                item["sentiment_score"] = float(score)
                                
                                logger.info(f"  ✅ Enriched: {item['title'][:20]}... (Sentiment: {score:.2f})")
                            else:
                                # Fallback: Use snippet for sentiment
                                logger.info(f"  ⚠️ Content short/failed for {item['url']}, using snippet for sentiment.")
                                text_to_analyze = f"{item['title']} {item['content']}" # content is snippet here
                                sent_result = self.sentiment_tool.analyze_sentiment(text_to_analyze)
                                score = sent_result.get('score', 0.0)
                                item["sentiment_score"] = float(score)

                        except Exception as e:
                             # Fallback: Use snippet for sentiment on error
                            logger.warning(f"Failed to enrich {item['url']}: {e}. Using snippet.")
                            text_to_analyze = f"{item['title']} {item['content']}"
                            sent_result = self.sentiment_tool.analyze_sentiment(text_to_analyze)
                            score = sent_result.get('score', 0.0)
                            item["sentiment_score"] = float(score)
            
            # 缓存结果 list
            if normalized_results:
                # Pass list directly, DB manager will handle JSON dump for main cache and populate search_details
                # Only cache if NOT from local news reuse (though this logic path is for fresh search)
                self.db.save_search_cache(query_hash, query, engine, normalized_results)
            
            return normalized_results
            
        except Exception as e:
            logger.error(f"❌ Structured search failed for {query}: {e}")
            return []

    def _evaluate_cache_relevance(self, current_query: str, candidates: List[Dict]) -> Dict:
        """
        使用 LLM 评估缓存候选是否足以回答当前问题。
        """
        try:
            # Prepare candidates text
            candidates_desc = []
            for i, c in enumerate(candidates):
                if c['type'] == 'cached_search':
                    # Preview cached results if available? 
                    # Maybe just use the query string as a proxy for what's in there.
                    # Or peek at 'results' snippet.
                    preview = ""
                    try:
                         # Attempt to peek first result title from JSON string
                         # Note: c.get('results') might be a stringified JSON list
                         res_list = json.loads(c.get('results', '[]'))
                         if res_list and isinstance(res_list, list) and len(res_list) > 0:
                             first_item = res_list[0]
                             if isinstance(first_item, dict) and 'title' in first_item:
                                 preview = f" (Contains: {first_item.get('title', '')[:50]}...)"
                    except:
                        pass
                    candidates_desc.append(f"[{i}] Old Search Query: '{c['query']}' {preview} (Time: {c['timestamp']})")
                elif c['type'] == 'local_news':
                     # List titles of local news
                     titles = [item['title'] for item in c['items'][:3]]
                     candidates_desc.append(f"[{i}] Local Database News: {', '.join(titles)}... (Time: {c['timestamp']})")

            prompt = f"""
            Task: Decide if existing information is sufficient for the new search query.
            
            New Query: "{current_query}"
            
            Available Information Candidates:
            {chr(10).join(candidates_desc)}
            
            Instructions:
            1. Analyze if any candidate provides ENOUGH up-to-date info for the "New Query".
            2. If yes, choose the best one.
            3. If the query implies needing LATEST real-time info and candidates are old, choose none.
            4. Return strictly JSON: {{"reuse": true/false, "index": <candidate_index_int>, "reason": "short explanation"}}
            """
            # 初始化模型
            provider = os.getenv("LLM_PROVIDER", "ust")
            model_id = os.getenv("LLM_MODEL", "Qwen")
            host = os.getenv("LLM_HOST")
            if host:
                model = get_model(provider, model_id, host=host)
            else:
                model = get_model(provider, model_id)
                
            agent = Agent(model=model, markdown=True)
            
            response = agent.run(prompt)
            content = response.content
            
            # Parse JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            elif '{' in content:
                 # Fallback for cases where LLM doesn't wrap in ```json
                 return json.loads(content[content.find('{'):content.rfind('}')+1])
            return {"reuse": False}
            
        except Exception as e:
            logger.warning(f"LLM evaluation failed: {e}")
            return {"reuse": False}

    def aggregate_search(self, query: str, engines: Optional[List[str]] = None, max_results: int = 5) -> str:
        """
        使用多个搜索引擎同时搜索并聚合结果，获得更全面的信息覆盖。
        
        Args:
            query: 搜索关键词。
            engines: 要使用的搜索引擎列表。可选值: ["ddg", "baidu"]。
                     默认同时使用 ddg 和 baidu。
            max_results: 每个引擎期望返回的结果数量。
        
        Returns:
            聚合后的搜索结果，按引擎分组显示。
        """
        engines = engines or ["ddg", "baidu"]
        aggregated_results = []
        for engine in engines:
            res = self.search(query, engine=engine, max_results=max_results)
            aggregated_results.append(f"--- Results from {engine.upper()} ---\n{res}")
        
        return "\n\n".join(aggregated_results)
