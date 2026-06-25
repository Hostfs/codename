import streamlit as st
import time

st.set_page_config(
    page_title="AI 시스템 자원 분석기",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# 세션 상태 초기화
# -----------------------------
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
        model = st.selectbox(
            "사용 모델",
            [
                "openai/gpt-4o-mini",
                "qwen/qwen-2.5-coder",
                "meta-llama/llama-3.1-8b-instruct"
            ]
        )

    with st.expander("Temperature", expanded=False):
        temperature = st.slider("Temperature", 0.0, 1.0, 0.7)

    with st.expander("Refresh", expanded=False):
        refresh_interval = st.selectbox(
            "대시보드 새로고침 주기",
            ["수동", "5초", "10초", "30초", "1분"]
        )

    with st.expander("Options", expanded=False):
        auto_analysis = st.checkbox("자동 AI 분석", value=True)
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
# AI 분석 요청 함수 자리
# -----------------------------
def request_ai_resource_analysis(user_prompt):
    """
    이 함수는 나중에 OpenRouter API와 연결할 자리입니다.

    실제 구현 흐름:
    1. 백그라운드 수집 모듈이 노트북 상태 정보를 가져옴
    2. 해당 정보를 OpenRouter LLM에 전달
    3. LLM이 CPU/RAM/GPU/저장소 상태를 자연어로 분석
    4. 결과를 화면에 출력
    """

    return f"""
### AI 시스템 분석 결과

현재 요청 내용: `{user_prompt}`

AI가 실시간으로 노트북의 프로세스 상태, CPU 사용 흐름, RAM 점유 상황,
GPU 사용 여부, 저장소 여유 공간 등을 분석한 뒤 결과를 제공하는 영역입니다.

#### 분석 항목
- CPU 자원 낭비 여부
- RAM을 많이 사용하는 프로세스
- GPU 사용이 필요한 작업 여부
- 저장소 정리 필요성
- 백그라운드 상주 프로그램 점검
- 종료 또는 비활성화 추천 프로세스

#### AI 조언 예시
현재 실행 중인 프로그램 중 사용 빈도는 낮지만 백그라운드에서 계속 실행되는 항목이 있다면,
이를 종료하거나 시작 프로그램에서 제외하는 방식으로 시스템 자원을 절약할 수 있습니다.
"""


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
        st.session_state.ai_system_summary = request_ai_resource_analysis(
            "현재 노트북 상태를 전체적으로 분석해줘."
        )
        st.success("AI 분석 요청이 생성되었습니다. AI 분석 화면에서 결과를 확인하세요.")


# -----------------------------
# 리소스 분석 화면
# -----------------------------
elif page == "리소스 분석":
    st.markdown('<div class="main-title">2. Resource Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">CPU, RAM, GPU, 저장소 수치를 직접 생성하지 않고, AI 분석 결과를 기반으로 시스템 상태를 표시합니다.</div>',
        unsafe_allow_html=True
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            """
            <div class="metric-card">
                <div class="metric-label">CPU 상태</div>
                <div class="metric-value">AI 분석 대기</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:
        st.markdown(
            """
            <div class="metric-card">
                <div class="metric-label">RAM 상태</div>
                <div class="metric-value">AI 분석 대기</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col3:
        st.markdown(
            """
            <div class="metric-card">
                <div class="metric-label">GPU 상태</div>
                <div class="metric-value">AI 분석 대기</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col4:
        st.markdown(
            """
            <div class="metric-card">
                <div class="metric-label">저장소 상태</div>
                <div class="metric-value">AI 분석 대기</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("### 프로세스 상태 표시창")

    st.info(
        "이 영역은 AI가 실시간으로 분석한 프로세스 상태를 표시하는 공간입니다. "
        "현재 코드는 random 값이나 내부 임시 데이터를 사용하지 않습니다."
    )

    if st.button("현재 노트북 리소스 AI 분석 요청", use_container_width=True):
        st.session_state.ai_resource_result = request_ai_resource_analysis(
            "현재 노트북의 CPU, RAM, GPU, 저장소 상태와 낭비되는 프로세스를 분석해줘."
        )

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
elif page == "AI 분석":
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

        ai_answer = request_ai_resource_analysis(user_input)

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
        with st.spinner("AI가 리포트를 생성하는 중입니다..."):
            time.sleep(1)

        st.session_state.ai_system_summary = request_ai_resource_analysis(
            "현재 노트북 상태를 바탕으로 최적화 리포트를 작성해줘."
        )

        st.success("리포트 생성 완료")
        st.markdown(st.session_state.ai_system_summary)