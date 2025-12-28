import numpy as np
from typing import List, Dict, Any, Optional, Union
from rank_bm25 import BM25Okapi
from loguru import logger

class HybridSearcher:
    """
    统一混合检索引擎 (Hybrid RAG)
    实现 BM25 (文本) + 向量 (语义) 的融合搜索 (RRF)
    """
    
    def __init__(self, data: List[Dict[str, Any]], text_fields: List[str] = ["title", "content"]):
        """
        初始化搜索器
        
        Args:
            data: 数据列表，每个元素为 Dict
            text_fields: 用于建立索引的文本字段
        """
        self.data = data
        self.text_fields = text_fields
        self._corpus = []
        self._bm25 = None
        self._fitted = False
        
        if data:
            self._prepare_corpus()
            self._fit_bm25()

    def _prepare_corpus(self):
        """准备语料库用于分词"""
        import jieba  # 使用 jieba 进行中文分词
        
        self._corpus = []
        for item in self.data:
            text = " ".join([str(item.get(field, "")) for field in self.text_fields])
            # 中文分词优化
            tokens = list(jieba.cut(text))
            self._corpus.append(tokens)

    def _fit_bm25(self):
        """训练 BM25 模型"""
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
            self._fitted = True
            logger.info(f"✅ BM25 index fitted with {len(self.data)} documents")

    def _compute_rrf(self, rank_lists: List[List[int]], k: int = 60) -> List[tuple]:
        """
        计算 Reciprocal Rank Fusion (RRF)
        
        Args:
            rank_lists: 多个排序后的索引列表
            k: RRF 常数，默认 60
        """
        scores = {}
        for rank_list in rank_lists:
            for rank, idx in enumerate(rank_list):
                if idx not in scores:
                    scores[idx] = 0
                scores[idx] += 1.0 / (k + rank + 1)
        
        # 按分数排序
        sorted_indices = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_indices

    def search(self, query: str, top_n: int = 5, use_vector: bool = False) -> List[Dict[str, Any]]:
        """
        执行混合搜索
        
        Args:
            query: 搜索关键词
            top_n: 返回结果数量
            use_vector: 是否启用向量搜索 (待进一步集成 Embedding 模型)
        """
        if not self._fitted or not query:
            return []
        
        import jieba
        query_tokens = list(jieba.cut(query))
        
        # 1. BM25 搜索结果
        bm25_scores = self._bm25.get_scores(query_tokens)
        bm25_rank = np.argsort(bm25_scores)[::-1].tolist()
        
        # 2. 如果启用向量，这里可以加入向量搜索逻辑
        rank_lists = [bm25_rank]
        
        if use_vector:
            # TODO: 集成 sentence-transformers 或 OpenAI Embedding
            logger.warning("Vector search is not fully implemented, falling back to BM25")
            # rank_lists.append(vector_rank)
        
        # 3. 融合排序 (RRF)
        if len(rank_lists) > 1:
            rrf_results = self._compute_rrf(rank_lists)
            # RRF 返回 (idx, score) 列表
            final_rank = [idx for idx, score in rrf_results]
        else:
            final_rank = bm25_rank
        
        # 返回前 top_n 条结果
        results = [self.data[idx] for idx in final_rank[:top_n]]
        
        # 为每个结果注入相关性评分 (占位)
        for i, res in enumerate(results):
            # 如果是纯 BM25，使用原始分数；如果是 RRF，暂无法直接映射原始分数，需特殊处理
            try:
                original_idx = final_rank[i]
                res["_search_score"] = bm25_scores[original_idx] 
            except:
                res["_search_score"] = 0
            
        return results

class InMemoryRAG(HybridSearcher):
    """专门用于 ReportAgent 跨章节检索的内存态 RAG"""
    
    def update_data(self, new_data: List[Dict[str, Any]]):
        """动态更新数据并重新训练索引"""
        self.data = new_data
        self._prepare_corpus()
        self._fit_bm25()
        logger.info(f"🔄 InMemoryRAG updated with {len(new_data)} items")

class LocalNewsSearch(HybridSearcher):
    """持久态 RAG：检索数据库中的历史新闻 (实现 Guide 2.2 章节建议)"""
    
    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 实例
        """
        self.db = db_manager
        # 初始时不加载数据，需调用 load_history
        super().__init__([], ["title", "content"])
    
    def load_history(self, days: int = 30):
        """从数据库加载最近 N 天的新闻构建索引"""
        try:
            # 假设 db_manager 有 execute_query
            query = f"SELECT title, content, publish_time, sentiment_score FROM daily_news ORDER BY publish_time DESC LIMIT 1000"
            results = self.db.execute_query(query)
            
            data = []
            for row in results:
                # 转换 Row 为 Dict
                item = dict(row) if hasattr(row, 'keys') else {
                    "title": row[0], "content": row[1], "publish_time": row[2]
                }
                data.append(item)
            
            self.data = data
            self._prepare_corpus()
            self._fit_bm25()
            logger.info(f"📚 LocalNewsSearch loaded {len(data)} items from history")
        except Exception as e:
            logger.error(f"Failed to load history for search: {e}")
