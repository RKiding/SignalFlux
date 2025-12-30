import torch
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional
from loguru import logger
from pandas.tseries.offsets import BusinessDay

# Fix for Kronos internal imports
import sys
import os
KRONOS_DIR = os.path.join(os.path.dirname(__file__), 'kronos')
if KRONOS_DIR not in sys.path:
    sys.path.append(KRONOS_DIR)

from utils.kronos.model import Kronos, KronosTokenizer, KronosPredictor
from schema.models import KLinePoint

class KronosPredictorUtility:
    """
    Kronos 时序预测工具类
    负责模型加载、推理以及数据结构转换
    """
    _instance = None
    _predictor = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KronosPredictorUtility, cls).__new__(cls)
        return cls._instance

    def __init__(self, device: Optional[str] = None):
        if self._predictor is not None:
            return
            
        try:
            if not device:
                device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            
            logger.info(f"🔮 Loading Kronos Model on {device}...")
            tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
            model = Kronos.from_pretrained("NeoQuasar/Kronos-base")
            
            tokenizer = tokenizer.to(device)
            model = model.to(device)
            
            self._predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
            logger.info("✅ Kronos Model loaded successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to load Kronos Model: {e}")
            self._predictor = None

    def get_base_forecast(self, df: pd.DataFrame, lookback: int = 20, pred_len: int = 5) -> List[KLinePoint]:
        """
        生成原始模型预测
        """
        if self._predictor is None:
            logger.error("Predictor not initialized.")
            return []

        if len(df) < lookback:
            logger.warning(f"Insufficient historical data ({len(df)}) for lookback ({lookback}).")
            return []

        # 获取最后 lookback 条数据
        x_df = df.iloc[-lookback:].copy()
        x_timestamp = pd.to_datetime(x_df['date']) # Ensure datetime
        last_date = x_timestamp.iloc[-1]
        
        # 生成未来时间戳
        future_dates = pd.date_range(start=last_date + BusinessDay(1), periods=pred_len, freq='B')
        y_timestamp = pd.Series(future_dates)

        try:
            # 预测所需的列
            cols = ['open', 'high', 'low', 'close', 'volume']
            pred_df = self._predictor.predict(
                df=x_df[cols],
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=1.0, 
                top_p=0.9, 
                sample_count=1,
                verbose=False
            )
            
            # 转换为 KLinePoint
            results = []
            for date, row in pred_df.iterrows():
                results.append(KLinePoint(
                    date=date.strftime("%Y-%m-%d"),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row['volume'])
                ))
            return results
        except Exception as e:
            logger.error(f"Forecast generation failed: {e}")
            return []

# Singleton instance for easy access
# Usage: predictor = KronosPredictorUtility()
