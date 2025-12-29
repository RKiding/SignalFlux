import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from utils.database_manager import DatabaseManager
from tools.toolkits import StockToolkit

def test_stock_data_context():
    print("🚀 Starting Stock Data Context Verification (Post-Fix)...")
    
    try:
        db = DatabaseManager()
    except Exception as e:
        print(f"Database init failed: {e}")
        return

    toolkit = StockToolkit(db)
    ticker = "000002" # Vanke A
    
    print(f"\n📡 Invoking get_stock_price('{ticker}')...")
    result = toolkit.get_stock_price(ticker)
    
    print("\n📄 [LLM Context Output Start]")
    print(result)
    print("📄 [LLM Context Output End]")
    
    # 验证是否包含表格数据
    if "OHLCV" in result and "|" in result:
        print("\n✅ SUCCESS: Detailed historical data table found in output!")
        print("   The LLM now has visibility into daily price movements.")
    elif "OHLCV" in result:
        print("\n✅ SUCCESS: Historical data section found (using plain text format).")
    else:
        print("\n❌ FAILED: Historical data missing.")

if __name__ == "__main__":
    test_stock_data_context()
