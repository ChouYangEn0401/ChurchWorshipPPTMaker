import traceback

if __name__ == "__main__":
    try:
        # 測試區邏輯
        print("Experimental Testing")
    except Exception as e:
        # 捕獲並顯示詳細錯誤資訊
        print("\n[Error Occurred]")
        traceback.print_exc()
    finally:
        # 確保程序結束時提供緩衝時間
        input("\n程序已結束。按 Enter 鍵退出...")
