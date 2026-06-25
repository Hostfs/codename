import streamlit as st
from streamlit_option_menu import option_menu

st.set_page_config(
    page_title="AI 시스템 자원 분석기",
    layout="wide"
)

selected = option_menu(
    menu_title=None,
    options=["메인", "프로세스 상태", "LLM 채팅", "설정"],
    icons=["house", "cpu", "chat-dots", "gear"],
    orientation="horizontal",
)

if selected == "메인":
    st.title("AI 시스템 자원 분석기")
    st.write("컴퓨터 자원을 분석하고 AI가 최적화 방안을 추천합니다.")

elif selected == "프로세스 상태":
    st.title("프로세스 상태 표시창")
    st.write("CPU, RAM, GPU, 저장소 사용량을 표시합니다.")

elif selected == "LLM 채팅":
    st.title("LLM 채팅창")
    user_input = st.chat_input("AI에게 질문을 입력하세요.")

    if user_input:
        st.chat_message("user").write(user_input)
        st.chat_message("assistant").write("AI 분석 결과가 여기에 표시됩니다.")

elif selected == "설정":
    st.title("설정창")

    model = st.selectbox("사용 모델", ["openai/gpt-4o-mini", "qwen/qwen-2.5-coder"])
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7)
    refresh_interval = st.selectbox("대시보드 새로고침 주기", ["5초", "10초", "30초", "1분"])
    ai_interval = st.selectbox("AI 분석 주기", ["수동", "1분", "5분", "10분"])
    dark_mode = st.toggle("다크 모드")