import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
from docx import Document
import io

# --- 1. 기본 설정 및 디자인 ---
st.set_page_config(page_title="패페 워싱봇 v2.4", page_icon="✍️", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .stApp { background-color: #ffffff; }
    .main-title { font-size: 3.2rem; font-weight: 800; color: #000; letter-spacing: -0.1rem; line-height: 1.1; margin-bottom: 2rem; }
    .content-box { padding: 25px; border-radius: 0px; border: 1px solid #000; background-color: #fdfdfd; margin-bottom: 20px; white-space: pre-wrap; font-size: 1.1rem; line-height: 1.6; }
    .stButton>button { background-color: #000; color: #fff; border-radius: 0px; border: none; font-weight: 700; height: 3.5rem; transition: 0.3s; width: 100%; margin-bottom: 10px; }
    .stButton>button:hover { background-color: #333; color: #fff; border: none; }
    .section-title { font-size: 1.5rem; font-weight: 700; color: #000; margin-bottom: 15px; border-left: 5px solid #000; padding-left: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 세션 상태 초기화 ---
if 'res_wash' not in st.session_state: st.session_state.res_wash = ""
if 'res_make' not in st.session_state: st.session_state.res_make = ""
if 'res_thumb' not in st.session_state: st.session_state.res_thumb = ""

# --- 2. 데이터 및 API 연동 ---
def get_sheets_client():
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        return gspread.authorize(creds)
    except:
        return None

def load_data():
    client = get_sheets_client()
    if not client: return [], "데이터 로드 실패"
    try:
        spreadsheet = client.open("fastpaper IG like RPA")
        memes = spreadsheet.worksheet("밈").get_all_records()
        archive = spreadsheet.worksheet("rpa").get_all_values()
        style_samples = [row[7] for row in archive[1:31] if len(row) > 7 and row[7]]
        style = "\n\n".join(style_samples)
        return memes, style
    except Exception as e:
        return [], f"스타일 가이드를 불러올 수 없습니다: {e}"

def call_ai(prompt):
    api_key = st.secrets["openrouter_api_key"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-2.0-flash-001", 
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        return res.json()['choices'][0]['message']['content']
    except:
        return "연결 실패 또는 한도 초과입니다."

# --- 3. UI 레이아웃 ---
st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

memes, style_guide = load_data()
meme_context = "\n".join([f"- {m['keyword']}: {m['meaning']}" for m in memes])

col_in, col_out = st.columns([1, 1])

with col_in:
    st.markdown('<div class="section-title">1. 자료 입력</div>', unsafe_allow_html=True)
    raw_text = st.text_area("📄 텍스트 입력", height=300)
    user_guide = st.text_area("💡 AI 제작 가이드", height=150)

    st.markdown('---')
    st.markdown('<div class="section-title">2. 작업 실행</div>', unsafe_allow_html=True)
    strict_rule = "\n[⚠️ 규칙: 이모지 사용 절대 금지. 마크다운 형식 금지. 텍스트만 출력.]"

    b_wash = st.button("✨ 문구 워싱")
    b_make = st.button("✍️ 캡션 제작")
    b_thumb = st.button("🖼️ 썸네일 문구 추천")

with col_out:
    st.markdown('<div class="section-title">3. 결과물 확인</div>', unsafe_allow_html=True)
    
    # 수정사항 2: 결과물이 위로 쌓이도록 순서 배치 (최신이 맨 위)
    
    # 3) 썸네일 (가장 아래 배치 원하시면 순서 조절 가능)
    if b_thumb:
        if raw_text:
            with st.spinner("아이디어 쥐어 짜는 중..."):
                prompt = f"""당신은 패스트페이퍼의 시니어 에디터입니다.
                [가이드]
                - 20~30자 내외 한 줄로 8개 작성.
                - 8개 중 3개는 아래 밈 활용 및 설명 병기.
                - {strict_rule}
                [밈] {meme_context}
                [자료] {raw_text}
                """
                st.session_state.res_thumb = call_ai(prompt)
        else: st.warning("내용을 입력해주세요.")

    # 2) 캡션 제작
    if b_make:
        if raw_text:
            with st.spinner("대단한 캡션 제작 중..."):
                prompt = f"{strict_rule}\n\n[말투 가이드]\n{style_guide}\n\n[자료]\n{raw_text}\n\n위 자료로 인스타 캡션을 써줘. 이모지는 빼고, [말투 가이드]의 캡션들과 비슷한 길이로 간결하게 작성해."
                st.session_state.res_make = call_ai(prompt)
        else: st.warning("내용을 입력해주세요.")

    # 1) 문구 워싱
    if b_wash:
        if raw_text:
            with st.spinner("열심히 워싱 중..."):
                # 수정사항 1: 워싱 길이 제한 강화
                prompt = f"{strict_rule}\n\n[말투 가이드]\n{style_guide}\n\n[원본]\n{raw_text}\n\n수정사항: [기존문구]와 [워싱결과]로 구분해줘. 특히 [워싱결과]는 [말투 가이드]에 있는 캡션들의 평균적인 길이(너무 길지 않게)를 반드시 준수해."
                st.session_state.res_wash = call_ai(prompt)
        else: st.warning("내용을 입력해주세요.")

    # --- 화면 출력 순서 (역순) ---
    if st.session_state.res_thumb:
        st.markdown(f'<div class="content-box"><strong>[썸네일 문구 제안]</strong>\n\n{st.session_state.res_thumb}</div>', unsafe_allow_html=True)
        
    if st.session_state.res_make:
        st.markdown(f'<div class="content-box"><strong>[제작된 캡션]</strong>\n\n{st.session_state.res_make}</div>', unsafe_allow_html=True)
        
    if st.session_state.res_wash:
        st.markdown(f'<div class="content-box"><strong>[문구 워싱 결과]</strong>\n\n{st.session_state.res_wash}</div>', unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 Fastpaper Washing Bot v2.4")
