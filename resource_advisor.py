import os
import sys
import json
import time
import subprocess
import pandas as pd

try:
    import streamlit as st
    from resource_advisor_command import execute_action
except ImportError as e:
    print(f"ImportError: {e}. Running patch to install missing modules...")
    subprocess.check_call([sys.executable, os.path.join(os.path.dirname(__file__), "patch.py")])
    os.execl(sys.executable, sys.executable, *sys.argv)

STATE_FILE = "shared_state.json"

st.set_page_config(page_title="시스템 자원 AI 어드바이저", page_icon="🖥️", layout="wide")

def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

state = load_state()

if not state:
    st.warning("백그라운드 워커(`background_worker.py`)가 실행되지 않았거나 데이터를 수집 중입니다. 터미널에서 워커를 실행해 주세요.")
    if st.button("새로고침"):
        st.rerun()
    st.stop()

# =========================================================
# 화면 헤더
# =========================================================
st.title("🖥️ 시스템 자원 AI 어드바이저")
st.caption(f"마지막 갱신: {state.get('last_update_str', '알 수 없음')}")

col1, col2 = st.columns([1, 10])
with col1:
    if st.button("🔄 새로고침"):
        st.rerun()

st.divider()

# =========================================================
# AI 조치 승인 UI (가장 상단 배치)
# =========================================================
pending_actions = state.get("pending_actions", [])
if pending_actions:
    st.error("⚠️ AI가 시스템 최적화를 위한 조치를 제안했습니다. 신중히 확인 후 승인해 주세요.")
    
    for act in pending_actions:
        st.markdown(f"- **[{act['type']}]** `{act['target']}`")
        
    if st.button("🚨 제안된 조치 실행 승인", type="primary"):
        for act in pending_actions:
            success, msg = execute_action(act["type"], act["target"])
            if success:
                st.success(f"{act['target']}: {msg}")
            else:
                st.error(f"{act['target']} 실패: {msg}")
        
        # 실행 후 알림이 계속 뜨는 것을 방지하기 위해 state 임시 비우기
        state["pending_actions"] = []
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except:
            pass

# =========================================================
# 대시보드 (자원 현황)
# =========================================================
snap = state.get("snapshot", {})
if snap:
    c1, c2 = st.columns(2)
    with c1:
        st.metric("CPU 사용률", f"{snap.get('cpu_percent', 0):.1f}%")
    with c2:
        mem_pct = snap.get('mem_percent', 0)
        used = snap.get('mem_used_gb', 0)
        total = snap.get('mem_total_gb', 0)
        st.metric("RAM 사용률", f"{mem_pct:.1f}%", f"{used:.1f} / {total:.1f} GB", delta_color="off")
        
    st.markdown("### 상위 프로세스 현황")
    
    t_c1, t_c2 = st.columns(2)
    with t_c1:
        st.markdown("**CPU 점유율 상위**")
        df_cpu = pd.DataFrame(snap.get("top_cpu", []))
        if not df_cpu.empty:
            st.dataframe(df_cpu[["name", "pid", "cpu_percent", "mem_percent"]], use_container_width=True, hide_index=True)
            
    with t_c2:
        st.markdown("**메모리 점유율 상위**")
        df_mem = pd.DataFrame(snap.get("top_mem", []))
        if not df_mem.empty:
            st.dataframe(df_mem[["name", "pid", "cpu_percent", "mem_percent"]], use_container_width=True, hide_index=True)

# =========================================================
# AI 분석 결과
# =========================================================
st.divider()
st.markdown("### 🤖 AI 상세 분석 리포트")
st.markdown(state.get("analysis_result", "아직 분석 결과가 없습니다. (최대 1분 소요)"))
