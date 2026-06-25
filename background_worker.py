import os
import sys
import time
import json
import threading
import subprocess
import traceback
from datetime import datetime

from dotenv import load_dotenv

# Missing modules handler
try:
    from win11toast import toast
    from resource_core import ResourceMonitor, snapshot_to_text, ask_llm, AVAILABLE_MODELS
    from resource_advisor_command import parse_actions
except ImportError as e:
    print(f"ImportError: {e}. Running patch to install missing modules...")
    subprocess.check_call([sys.executable, os.path.join(os.path.dirname(__file__), "patch.py")])
    print("Restarting application...")
    os.execl(sys.executable, sys.executable, *sys.argv)

load_dotenv()

STATE_FILE = "shared_state.json"
CHECK_INTERVAL_SEC = 2
ANALYSIS_INTERVAL_SEC = 60

def save_state(snapshot, analysis_result, pending_actions):
    state = {
        "snapshot": snapshot,
        "analysis_result": analysis_result,
        "pending_actions": pending_actions,
        "last_update": time.time(),
        "last_update_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    # 임시 파일에 먼저 쓰고 원본을 덮어씌워 충돌을 최소화
    temp_file = STATE_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        print(f"Failed to save state: {e}")

def notify_user(actions):
    """Notify the user via Toast that AI wants to take action."""
    try:
        action_texts = [f"[{a['type']}] {a['target']}" for a in actions]
        msg = "시스템 조치 승인이 필요합니다.\n" + "\n".join(action_texts)
        
        # 버튼을 클릭하면 localhost:8501이 열리도록 설정
        button = {
            "activationType": "protocol",
            "arguments": "http://localhost:8501",
            "content": "자세히 보기 및 승인"
        }
        
        result = toast("⚠️ 시스템 자원 어드바이저", msg, buttons=[button], audio={"src": "ms-winsoundevent:Notification.Default"})
        if result and isinstance(result, tuple) and "HResult" in str(result):
            raise Exception(f"Toast HResult Error: {result}")
            
    except Exception as e:
        print(f"Toast 알림 전송 실패(방해 금지 모드 등), 팝업으로 대체합니다: {e}")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            messagebox.showwarning("⚠️ 시스템 자원 어드바이저 경고", msg + "\n\n웹 대시보드(http://localhost:8501)를 열어 승인해 주세요!")
            root.destroy()
        except Exception as fallback_e:
            print(f"팝업 전송도 실패했습니다: {fallback_e}")

def main():
    print("========================================")
    print(" 백그라운드 모니터링 데몬 실행 중...")
    print(" - 이 창을 닫지 마세요.")
    print(" - 문제가 발생하면 윈도우 알림이 뜹니다.")
    print("========================================")
    
    if not os.getenv("OPENROUTER_API_KEY"):
        print("경고: .env 파일에 OPENROUTER_API_KEY가 없습니다.")
    
    monitor = ResourceMonitor()
    last_analysis_time = 0
    current_analysis_result = ""
    current_pending_actions = []
    
    # 기본 모델 사용
    model = AVAILABLE_MODELS[0]
    
    while True:
        try:
            # 1. 스냅샷 수집
            snapshot = monitor.get_snapshot()
            
            # 2. AI 분석 주기가 되었는지 확인
            now = time.time()
            if now - last_analysis_time >= ANALYSIS_INTERVAL_SEC:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] AI 분석을 시작합니다... (모델: {model})")
                last_analysis_time = now
                
                text = snapshot_to_text(snapshot)
                analysis_result = ask_llm(text, model, 0.3)
                actions = parse_actions(analysis_result)
                
                # 조치가 이전과 동일한지 확인하여 중복 알림 방지
                old_targets = {a['target'] for a in current_pending_actions}
                new_targets = {a['target'] for a in actions}
                
                current_analysis_result = analysis_result
                current_pending_actions = actions
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] AI 분석 완료.")
                
                if actions and new_targets != old_targets:
                    print(f"  -> 새로운 조치 제안 발견! Toast 알림을 전송합니다.")
                    threading.Thread(target=notify_user, args=(actions,), daemon=True).start()
            
            # 3. 상태 저장 (Streamlit이 읽을 수 있게)
            save_state(snapshot, current_analysis_result, current_pending_actions)
            
        except Exception as e:
            print(f"에러 발생: {e}")
            traceback.print_exc()
            
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    main()
