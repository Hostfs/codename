import time

import streamlit as st

from resource_core import OPENROUTER_API_KEY, AVAILABLE_MODELS, ResourceMonitor, snapshot_to_text, ask_llm, load_whitelist, save_whitelist
from resource_advisor_command import execute_action, parse_actions

# =========================================================
# 1. 페이지 / 세션 상태 초기화
# =========================================================
st.set_page_config(
    page_title="시스템 자원 AI 어드바이저",
    page_icon="🖥️",
    layout="wide"
)

if "monitor" not in st.session_state:
    st.session_state.monitor = ResourceMonitor()

if "last_snapshot" not in st.session_state:
    st.session_state.last_snapshot = None

if "last_analysis" not in st.session_state:
    st.session_state.last_analysis = None

if "last_analysis_time" not in st.session_state:
    st.session_state.last_analysis_time = 0.0

if "pending_actions" not in st.session_state:
    st.session_state.pending_actions = []

# =========================================================
# 2. 사이드바
# =========================================================
with st.sidebar:
    st.title("⚙️ 설정")

    selected_model = st.selectbox("사용 모델", AVAILABLE_MODELS)

    temperature = st.slider("Temperature", 0.0, 1.0, 0.3, 0.1)

    refresh_interval = st.slider(
        "대시보드 새로고침 주기 (초)", 1, 30, 1,
        help="CPU/RAM/GPU 수치를 갱신하는 주기입니다."
    )

    st.divider()

    auto_analyze = st.toggle("AI 자동 분석", value=False)

    analysis_interval = st.slider(
        "AI 분석 주기 (초)", 30, 600, 60, 30,
        help="자동 분석 시 LLM을 호출하는 주기입니다. API 비용이 발생하므로 너무 짧게 설정하지 마세요.",
        disabled=not auto_analyze
    )

    manual_analyze = st.button("지금 분석하기", width="stretch", type="primary")

    st.caption("OpenRouter API를 사용하므로 분석 요청마다 비용이 발생할 수 있습니다.")

    st.divider()
    st.header("🛡️ 예외 처리 (Whitelist)")
    st.write("사용자가 의도적으로 실행 중인 무거운 프로세스 목록입니다. AI가 이 프로세스들은 종료를 제안하지 않습니다.")
    
    whitelist = load_whitelist()
    if whitelist:
        for p_name in whitelist:
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.code(p_name)
            with col_b:
                if st.button("❌", key=f"del_{p_name}"):
                    whitelist.remove(p_name)
                    save_whitelist(whitelist)
                    st.rerun()
    else:
        st.info("등록된 예외 프로세스가 없습니다.")

# =========================================================
# 3. 대시보드 (주기적 갱신)
# =========================================================
st.title("🖥️ 시스템 자원 AI 어드바이저")
st.caption("CPU / RAM / GPU / 디스크 사용량을 실시간으로 확인하고 AI에게 최적화 조언을 받습니다.")


def get_process_name_from_pid(pid_str, snap):
    try:
        pid = int(pid_str)
        # top_cpu와 top_mem을 모두 뒤져서 이름을 찾습니다
        for p in snap.get("top_cpu", []) + snap.get("top_mem", []):
            if p["pid"] == pid:
                return p["name"]
    except:
        pass
    return None

pending_actions = st.session_state.get("pending_actions", [])
snap = st.session_state.last_snapshot

if pending_actions:
    st.error("⚠️ AI가 시스템 최적화를 위한 조치를 제안했습니다. 신중히 확인 후 승인해 주세요.")
    
    whitelist = load_whitelist()
    for act in pending_actions:
        p_name = get_process_name_from_pid(act['target'], snap) if act['type'] == 'KILL_PROCESS' and snap else None
        
        col_act1, col_act2 = st.columns([3, 1])
        with col_act1:
            st.markdown(f"- **[{act['type']}]** `{act['target']}` " + (f"({p_name})" if p_name else ""))
        with col_act2:
            if p_name and p_name not in whitelist:
                if st.button("✅ 의도된 작업입니다 (예외 등록)", key=f"ignore_{act['target']}"):
                    whitelist.append(p_name)
                    save_whitelist(whitelist)
                    st.success(f"'{p_name}' 프로세스가 화이트리스트에 등록되었습니다!")
                    st.rerun()
        
    if st.button("🚨 제안된 조치 실행 일괄 승인", type="primary"):
        for act in pending_actions:
            success, msg = execute_action(act["type"], act["target"])
            if success:
                st.success(f"{act['target']}: {msg}")
            else:
                st.error(f"{act['target']} 실패: {msg}")
        
        st.session_state.pending_actions = []
        st.rerun()


@st.fragment(run_every=refresh_interval)
def show_dashboard():
    snap = st.session_state.monitor.get_snapshot()
    st.session_state.last_snapshot = snap

    st.caption(f"마지막 갱신: {snap['timestamp']}")

    col1, col2 = st.columns(2)
    col1.metric("CPU 사용률", f"{snap['cpu_percent']:.1f}%")
    col2.metric("RAM 사용률", f"{snap['mem_percent']:.1f}%", f"{snap['mem_used_gb']:.1f} / {snap['mem_total_gb']:.1f} GB")

    st.markdown("##### 디스크")
    disk_cols = st.columns(len(snap["disks"]) or 1)
    for c, d in zip(disk_cols, snap["disks"]):
        c.metric(d["mount"], f"{d['percent']:.1f}%", f"{d['used_gb']:.1f} / {d['total_gb']:.1f} GB")

    st.markdown("##### GPU")
    if snap["gpus"]:
        gpu_cols = st.columns(len(snap["gpus"]))
        for c, g in zip(gpu_cols, snap["gpus"]):
            if g.get("static_only"):
                c.metric(g["name"], "감지됨", f"VRAM: {g['mem_total_mb']:.0f} MB")
            else:
                temp_txt = f", {g['temp_c']:.0f}C" if g.get("temp_c") is not None else ""
                c.metric(g["name"], f"{g['util_percent']:.0f}%", f"{g['mem_used_mb']:.0f} / {g['mem_total_mb']:.0f} MB{temp_txt}")
    else:
        st.info("GPU 정보를 가져올 수 없습니다.")

    col_cpu, col_mem = st.columns(2)
    with col_cpu:
        st.markdown("###### CPU 사용량 상위 프로세스")
        st.dataframe(snap["top_cpu"], hide_index=True, width="stretch")
    with col_mem:
        st.markdown("###### 메모리 사용량 상위 프로세스")
        st.dataframe(snap["top_mem"], hide_index=True, width="stretch")


show_dashboard()

st.divider()

# =========================================================
# 4. AI 분석 (자동 주기 또는 수동 버튼)
# =========================================================
st.subheader("🤖 AI 분석")


@st.fragment(run_every=analysis_interval if auto_analyze else None)
def run_auto_analysis():
    if not auto_analyze:
        return
    now = time.time()
    if now - st.session_state.last_analysis_time < analysis_interval - 1:
        return
    if st.session_state.last_snapshot is None:
        return

    with st.spinner("AI가 자원 사용 현황을 분석하고 있습니다..."):
        try:
            text = snapshot_to_text(st.session_state.last_snapshot, whitelist=load_whitelist())
            st.session_state.last_analysis = ask_llm(text, selected_model, temperature)
            st.session_state.pending_actions = parse_actions(st.session_state.last_analysis)
            st.session_state.last_analysis_time = now
        except Exception as e:
            st.session_state.last_analysis = f"분석 중 오류가 발생했습니다: {e}"


if manual_analyze:
    if not OPENROUTER_API_KEY:
        st.error(".env 파일에 OPENROUTER_API_KEY가 설정되어 있지 않습니다.")
    elif st.session_state.last_snapshot is None:
        st.warning("아직 수집된 자원 데이터가 없습니다. 잠시 후 다시 시도하세요.")
    else:
        with st.spinner("AI가 자원 사용 현황을 분석하고 있습니다..."):
            try:
                text = snapshot_to_text(st.session_state.last_snapshot, whitelist=load_whitelist())
                st.session_state.last_analysis = ask_llm(text, selected_model, temperature)
                st.session_state.pending_actions = parse_actions(st.session_state.last_analysis)
                st.session_state.last_analysis_time = time.time()
                st.rerun()
            except Exception as e:
                st.error("API 호출 중 오류가 발생했습니다.")
                st.code(str(e))

run_auto_analysis()

if st.session_state.last_analysis:
    st.markdown(st.session_state.last_analysis)
else:
    st.info("‘지금 분석하기’ 버튼을 누르거나 자동 분석을 켜면 AI 조언이 여기에 표시됩니다.")

with st.expander("LLM에 전달된 마지막 데이터 보기"):
    if st.session_state.last_snapshot:
        st.code(snapshot_to_text(st.session_state.last_snapshot, whitelist=load_whitelist()))
