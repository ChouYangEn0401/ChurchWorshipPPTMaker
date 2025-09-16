import traceback
import os

# 定義輸出資料夾
DATA_FOLDER = "data"

# 確保資料夾存在
os.makedirs(DATA_FOLDER, exist_ok=True)

if __name__ == "__main__":
    try:
        # 主程序邏輯放在這裡
        print("Hello World")
    except Exception as e:
        # 捕獲並顯示詳細錯誤資訊
        print("\n[Error Occurred]")
        traceback.print_exc()
    finally:
        # 確保程序結束時提供緩衝時間
        input("\n程序已結束。按 Enter 鍵退出...")
