import streamlit as st
import time
import os
from resource_core import (
    OPENROUTER_API_KEY,
    AVAILABLE_MODELS,
    ResourceMonitor,
    snapshot_to_text,
    ask_llm,
    ask_llm_question,
    load_whitelist,
    save_whitelist,
)
from resource_advisor_command import execute_action, parse_actions

st.set_page_config(
    page_title="AI 시스템 자원 분석기",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# 세션 상태 초기화
# -----------------------------
if "monitor" not in st.session_state:
    st.session_state.monitor = ResourceMonitor()

if "last_snapshot" not in st.session_state:
    st.session_state.last_snapshot = None

if "last_analysis" not in st.session_state:
    st.session_state.last_analysis = None

if "pending_actions" not in st.session_state:
    st.session_state.pending_actions = []

if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

if "ai_system_summary" not in st.session_state:
    st.session_state.ai_system_summary = None

if "ai_resource_result" not in st.session_state:
    st.session_state.ai_resource_result = None

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "안녕하세요. 현재 노트북 상태를 분석하고 최적화 방안을 추천해드릴게요."
        }
    ]


# -----------------------------
# 사이드바
# -----------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-title">
            AI<br>Resource<br>Manager
        </div>
        """,
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)
    with col1:
        st.link_button("GitHub", "https://github.com/Hostfs/codename")
    with col2:
        st.link_button("Guide", "https://streamlit.io")

    st.caption("(Open in a new tab)")
    st.divider()

    st.header("1. Menu")

    page = st.radio(
        "페이지 선택",
        ["홈", "리소스 분석", "AI 채팅", "최적화 리포트"],
        label_visibility="collapsed"
    )

    st.header("2. AI Setting")

    with st.expander("Model", expanded=True):
        model = st.selectbox("사용 모델", AVAILABLE_MODELS)

    with st.expander("Temperature", expanded=False):
        temperature = st.slider("Temperature", 0.0, 1.0, 0.3)

    with st.expander("Refresh", expanded=False):
        refresh_interval = st.selectbox(
            "대시보드 새로고침 주기",
            ["5초", "10초", "30초", "1분", "수동"]
        )
        refresh_map = {"5초": 5, "10초": 10, "30초": 30, "1분": 60, "수동": None}
        ref_sec = refresh_map[refresh_interval]

    with st.expander("Options", expanded=False):
        st.checkbox("다크 모드", key="dark_mode")


# -----------------------------
# 다크모드 CSS 스타일
# -----------------------------
if st.session_state.dark_mode:
    bg_color = "#111827"
    sidebar_bg = "#1f2937"
    card_bg = "#1f2937"
    box_bg = "#1f2937"
    text_color = "#f9fafb"
    sub_text_color = "#d1d5db"
    border_color = "#374151"
    input_bg = "#374151"
else:
    bg_color = "#ffffff"
    sidebar_bg = "#f8f9fa"
    card_bg = "#f5f5f5"
    box_bg = "#fafafa"
    text_color = "#111827"
    sub_text_color = "#666666"
    border_color = "#e5e5e5"
    input_bg = "#ffffff"

st.markdown(f"""
<style>
    .stApp {{
        background-color: {bg_color};
        color: {text_color};
    }}

    [data-testid="stSidebar"] {{
        background-color: {sidebar_bg};
    }}

    [data-testid="stHeader"] {{
        background-color: {bg_color};
    }}

    .main-title {{
        font-size: 42px;
        font-weight: 800;
        margin-bottom: 8px;
        color: {text_color};
    }}

    .sub-title {{
        font-size: 17px;
        color: {sub_text_color};
        margin-bottom: 30px;
    }}

    .metric-card {{
        background-color: {card_bg};
        padding: 24px;
        border-radius: 16px;
        border: 1px solid {border_color};
        text-align: center;
        min-height: 130px;
    }}

    .metric-label {{
        font-size: 15px;
        color: {sub_text_color};
    }}

    .metric-value {{
        font-size: 26px;
        font-weight: 800;
        margin-top: 10px;
        color: {text_color};
    }}

    .section-box {{
        background-color: {box_bg};
        padding: 24px;
        border-radius: 18px;
        border: 1px solid {border_color};
        margin-top: 18px;
        color: {text_color};
    }}

    .section-box h3 {{
        color: {text_color};
    }}

    .section-box p,
    .section-box li {{
        color: {sub_text_color};
    }}

    .sidebar-title {{
        font-size: 28px;
        font-weight: 800;
        line-height: 1.2;
        margin-bottom: 20px;
        color: {text_color};
    }}

    h1, h2, h3, h4, h5, h6 {{
        color: {text_color};
    }}

    p, label, span, div {{
        color: {text_color};
    }}

    .stMarkdown {{
        color: {text_color};
    }}

    [data-testid="stMetric"] {{
        background-color: {card_bg};
        border: 1px solid {border_color};
        padding: 16px;
        border-radius: 14px;
    }}

    [data-testid="stMetricLabel"] {{
        color: {sub_text_color};
    }}

    [data-testid="stMetricValue"] {{
        color: {text_color};
    }}

    .stTextInput input,
    .stTextArea textarea,
    .stSelectbox div,
    .stNumberInput input {{
        background-color: {input_bg};
        color: {text_color};
    }}

    div[data-testid="stInfo"] {{
        background-color: {box_bg};
        color: {text_color};
        border: 1px solid {border_color};
    }}

    div[data-testid="stSuccess"] {{
        border-radius: 12px;
    }}
</style>
""", unsafe_allow_html=True)


# -----------------------------
# 헬퍼 함수
# -----------------------------
def get_process_name_from_pid(pid_str, snap):
    try:
        pid = int(pid_str)
        for p in snap.get("top_cpu", []) + snap.get("top_mem", []):
            if p["pid"] == pid:
                return p["name"]
    except:
        pass
    return None


# -----------------------------
# 홈 화면
# -----------------------------
if page == "홈":
    st.markdown('<div class="main-title">1. Overview</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">AI가 노트북의 시스템 상태를 실시간으로 분석하고, 낭비되는 자원과 최적화 방안을 추천합니다.</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### More info on this system")
        st.markdown(
            """
            <div class="section-box">
                <h3>AI 기반 시스템 자원 분석 어시스턴트</h3>
                <p>
                본 서비스는 노트북의 프로세스 상태와 자원 사용 흐름을 AI가 분석하여,
                사용자가 이해하기 쉬운 형태로 현재 시스템 상태를 설명합니다.
                </p>
                <p>
                단순히 임의의 수치를 표시하는 것이 아니라,
                LLM이 자원 낭비 가능성, 비효율적인 프로세스 사용, 정리 필요 항목을 해석해 조언합니다.
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:
        st.markdown("### AI Status")
        st.metric("분석 방식", "LLM 기반")
        st.metric("분석 대상", "실시간 노트북 상태")
        st.metric("데이터 표시", "AI 분석 결과 기반")

    st.divider()

    if st.button("AI 시스템 분석 시작하기", use_container_width=True):
        if not OPENROUTER_API_KEY:
            st.error(".env 파일에 OPENROUTER_API_KEY가 설정되어 있지 않습니다.")
        else:
            with st.spinner("AI가 자원 사용 현황을 분석하고 있습니다..."):
                snap = st.session_state.monitor.get_snapshot()
                st.session_state.last_snapshot = snap
                text = snapshot_to_text(snap, whitelist=load_whitelist())
                try:
                    res = ask_llm(text, model, temperature)
                    st.session_state.ai_system_summary = res
                    st.session_state.pending_actions = parse_actions(res)
                    st.success("AI 시스템 전체 분석이 완료되었습니다. '리소스 분석' 또는 '최적화 리포트' 화면에서 상세 내용을 확인하세요.")
                except Exception as e:
                    st.error(f"분석 중 오류 발생: {e}")


# -----------------------------
# 리소스 분석 화면
# -----------------------------
elif page == "리소스 분석":
    st.markdown('<div class="main-title">2. Resource Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">CPU, RAM, GPU, 저장소 수치 및 프로세스 리스트를 실시간으로 모니터링하고 AI 분석을 요청합니다.</div>',
        unsafe_allow_html=True
    )

    # ── 조치 제안 카드 (승인 대기) ──
    pending_actions = st.session_state.get("pending_actions", [])
    snap = st.session_state.last_snapshot
    
    if pending_actions:
        st.error("⚠️ AI가 시스템 최적화를 위한 조치를 제안했습니다. 신중히 확인 후 승인해 주세요.")
        
        whitelist = load_whitelist()
        filtered_actions = []
        
        for act in pending_actions:
            p_name = get_process_name_from_pid(act['target'], snap) if act['type'] == 'KILL_PROCESS' and snap else None
            
            # 화이트리스트 필터링
            if act['type'] == 'KILL_PROCESS' and p_name and p_name in whitelist:
                continue
            if act['type'] == 'DELETE_FILE' and act['target'] in whitelist:
                continue
                
            filtered_actions.append(act)
            
            col_act1, col_act2 = st.columns([3, 1])
            with col_act1:
                st.markdown(f"- **[{act['type']}]** `{act['target']}` " + (f"({p_name})" if p_name else ""))
            with col_act2:
                if act['type'] == 'KILL_PROCESS' and p_name:
                    if st.button("✅ 예외 등록", key=f"ignore_{act['target']}_{p_name}"):
                        whitelist.append(p_name)
                        save_whitelist(whitelist)
                        st.success(f"'{p_name}' 프로세스가 화이트리스트에 등록되었습니다!")
                        st.rerun()
                elif act['type'] == 'DELETE_FILE':
                    if st.button("✅ 예외 등록", key=f"ignore_{act['target']}"):
                        whitelist.append(act['target'])
                        save_whitelist(whitelist)
                        st.success(f"'{act['target']}' 파일이 화이트리스트에 등록되었습니다!")
                        st.rerun()
        
        if filtered_actions:
            if st.button("🚨 제안된 조치 실행 일괄 승인", type="primary", use_container_width=True):
                for act in filtered_actions:
                    success, msg = execute_action(act["type"], act["target"])
                    if success:
                        st.success(f"성공: {act['target']} - {msg}")
                    else:
                        st.error(f"실패: {act['target']} - {msg}")
                
                st.session_state.pending_actions = []
                st.rerun()

    # ── 실시간 대시보드 렌더링 ──
    @st.fragment(run_every=ref_sec)
    def render_live_dashboard():
        live_snap = st.session_state.monitor.get_snapshot()
        st.session_state.last_snapshot = live_snap
        
        # 지표 카드 계산
        cpu_val = f"{live_snap['cpu_percent']:.1f}%"
        ram_val = f"{live_snap['mem_percent']:.1f}%"
        
        gpu_val = "N/A"
        if live_snap["gpus"]:
            gpu = live_snap["gpus"][0]
            if gpu.get("static_only"):
                gpu_val = "감지됨"
            else:
                gpu_val = f"{gpu['util_percent']:.0f}%"
                
        disk_val = "N/A"
        if live_snap["disks"]:
            disk_val = f"{live_snap['disks'][0]['percent']:.1f}%"
            
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<div class="metric-card"><div class="metric-label">CPU 사용률</div><div class="metric-value">{cpu_val}</div></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><div class="metric-label">RAM 사용률</div><div class="metric-value">{ram_val}</div></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><div class="metric-label">GPU 사용률</div><div class="metric-value">{gpu_val}</div></div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<div class="metric-card"><div class="metric-label">주 디스크 사용률</div><div class="metric-value">{disk_val}</div></div>', unsafe_allow_html=True)
            
        st.markdown(f"<span style='color:gray; font-size:11px;'>대시보드 실시간 갱신: {live_snap['timestamp']}</span>", unsafe_allow_html=True)
        
        col_cpu, col_mem = st.columns(2)
        with col_cpu:
            st.markdown("### CPU 상위 프로세스")
            st.dataframe(live_snap["top_cpu"], hide_index=True, use_container_width=True)
        with col_mem:
            st.markdown("### 메모리 상위 프로세스")
            st.dataframe(live_snap["top_mem"], hide_index=True, use_container_width=True)
            
        col_disk, col_gpu = st.columns(2)
        with col_disk:
            st.markdown("### 디스크 목록")
            st.dataframe(live_snap["disks"], hide_index=True, use_container_width=True)
        with col_gpu:
            st.markdown("### GPU 정보")
            if live_snap["gpus"]:
                st.dataframe(live_snap["gpus"], hide_index=True, use_container_width=True)
            else:
                st.info("감지된 GPU 장치가 없습니다.")
                
    render_live_dashboard()

    st.divider()

    if st.button("현재 노트북 리소스 AI 분석 요청", use_container_width=True):
        if not OPENROUTER_API_KEY:
            st.error(".env 파일에 OPENROUTER_API_KEY가 설정되어 있지 않습니다.")
        elif st.session_state.last_snapshot is None:
            st.warning("아직 수집된 자원 데이터가 없습니다. 잠시 후 다시 시도하세요.")
        else:
            with st.spinner("AI가 자원 사용 현황을 분석하고 있습니다..."):
                text = snapshot_to_text(st.session_state.last_snapshot, whitelist=load_whitelist())
                try:
                    res = ask_llm(text, model, temperature)
                    st.session_state.ai_resource_result = res
                    st.session_state.pending_actions = parse_actions(res)
                    st.rerun()
                except Exception as e:
                    st.error(f"API 호출 중 오류 발생: {e}")

    if st.session_state.ai_resource_result:
        st.markdown(st.session_state.ai_resource_result)
    else:
        st.markdown(
            """
            <div class="section-box">
                <h3>AI 분석 결과 대기 중</h3>
                <p>
                분석 버튼을 누르면 AI가 현재 노트북 상태를 기반으로
                자원 사용 현황과 최적화 필요 항목을 설명합니다.
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )


# -----------------------------
# AI 분석 화면
# -----------------------------
elif page == "AI 채팅":
    st.markdown('<div class="main-title">3. LLM Analysis Chat</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">AI에게 현재 노트북 상태, 프로세스 관리, 자원 낭비 여부를 질문합니다.</div>',
        unsafe_allow_html=True
    )

    st.markdown("### LLM 채팅창")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    user_input = st.chat_input("예: 지금 노트북이 느린 이유를 분석해줘.")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        if not OPENROUTER_API_KEY:
            ai_answer = "⚠ OPENROUTER_API_KEY가 없습니다."
        else:
            snap_text = snapshot_to_text(st.session_state.last_snapshot, whitelist=load_whitelist()) if st.session_state.last_snapshot else ""
            with st.spinner("AI가 답변을 준비 중입니다..."):
                try:
                    ai_answer = ask_llm_question(snap_text, user_input, model, temperature)
                except Exception as e:
                    ai_answer = f"답변 중 오류 발생: {e}"

        st.session_state.messages.append({"role": "assistant", "content": ai_answer})
        with st.chat_message("assistant"):
            st.write(ai_answer)


# -----------------------------
# 최적화 리포트 화면
# -----------------------------
elif page == "최적화 리포트":
    st.markdown('<div class="main-title">4. Optimization Report</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">AI가 분석한 시스템 최적화 결과와 개선 방향을 리포트 형태로 제공합니다.</div>',
        unsafe_allow_html=True
    )

    st.markdown("### 최적화 요약")

    if st.session_state.ai_system_summary:
        st.markdown(st.session_state.ai_system_summary)
    else:
        st.info("아직 생성된 AI 분석 리포트가 없습니다. 홈 또는 AI 분석 화면에서 분석을 먼저 실행하세요.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            """
            <div class="section-box">
                <h3>AI가 점검할 항목</h3>
                <ul>
                    <li>CPU를 과도하게 사용하는 프로세스</li>
                    <li>RAM을 장시간 점유하는 프로그램</li>
                    <li>GPU 사용이 불필요한 작업</li>
                    <li>저장소 공간을 차지하는 임시 파일</li>
                    <li>사용 후에도 남아 있는 상주 프로그램</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:
        st.markdown(
            """
            <div class="section-box">
                <h3>AI 추천 방향</h3>
                <ul>
                    <li>불필요한 프로세스 종료 추천</li>
                    <li>시작 프로그램 정리 제안</li>
                    <li>백그라운드 프로그램 점검</li>
                    <li>저장소 정리 우선순위 안내</li>
                    <li>작업 목적에 맞는 최적화 방법 제안</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("### 리포트 생성")

    if st.button("AI 최적화 리포트 생성", use_container_width=True):
        if not OPENROUTER_API_KEY:
            st.error(".env 파일에 OPENROUTER_API_KEY가 설정되어 있지 않습니다.")
        else:
            with st.spinner("AI가 리포트를 생성하는 중입니다..."):
                snap = st.session_state.monitor.get_snapshot()
                st.session_state.last_snapshot = snap
                text = snapshot_to_text(snap, whitelist=load_whitelist())
                try:
                    res = ask_llm(text, model, temperature)
                    st.session_state.ai_system_summary = res
                    st.session_state.pending_actions = parse_actions(res)
                    st.success("리포트 생성 완료")
                    st.rerun()
                except Exception as e:
                    st.error(f"리포트 생성 실패: {e}")