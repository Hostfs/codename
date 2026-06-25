import time
import os

def main():
    print("==========================================")
    print(f"⚠️ Memory Hog Process Started!")
    print(f"▶️ PID: {os.getpid()}")
    print("==========================================")
    print("Allocating memory...")

    # 약 2GB의 메모리를 할당합니다.
    hog = []
    try:
        for i in range(200): # 200 * 10MB = 2000MB = 2GB
            hog.append(b"0" * (10 * 1024 * 1024))
            if (i + 1) % 20 == 0:
                print(f"Allocated {(i + 1) * 10} MB...")
                
        print("\n✅ Memory allocation complete (approx 2GB).")
        print("Holding memory. Check your Resource Advisor app now!")
        print("(Press Ctrl+C to stop manually)")
        
        # 프로세스가 종료되지 않도록 무한 대기
        while True:
            time.sleep(10)
            
    except MemoryError:
        print("\n❌ Memory limit reached! Holding what we have...")
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
