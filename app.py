import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import json

# --- 1. 기본 설정 및 디자인 ---
st.set_page_config(page_title="패페 워싱봇 v2.6", page_icon="✍️", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .stApp { background-color: #ffffff; }
    .main-title { font-size: 3.2rem; font-weight: 800; color: #000; letter-spacing: -0.1rem; line-height: 1.1; margin-bottom: 2rem; }
    .content-box { padding: 25px; border-radius: 0px; border: 1px solid #000; background-color: #fdfdfd; margin-bottom: 20px; white-space: pre-wrap; font-size: 1.1rem; line-height: 1.6; }
    .stButton>button { background-color: #000; color: #fff; border-radius: 0px; border: none; font-weight: 700; height: 3.5rem; transition: 0.3s; width: 100%; margin-bottom: 10px; }
    .stButton>button:hover { background-color: #333; color: #fff; border: none; }
    .refresh-btn>div>button { background-color: #fff !important; color: #ff4b4b !important; border: 1px solid #ff4b4b !important; }
    .refresh-btn>div>button:hover { background-color: #ff4b4b !important; color: #fff !important; }
    .section-title { font-size: 1.5rem; font-weight: 700; color: #000; margin-bottom: 15px; border-left: 5px solid #000; padding-left: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 세션 상태 초기화 ---
if 'res_wash' not in st.session_state: st.session_state.res_wash = ""
if 'res_make' not in st.session_state: st.session_state.res_make = ""
if 'res_thumb' not in st.session_state: st.session_state.res_thumb = ""

def reset_results():
    st.session_state.res_wash = ""
    st.session_state.res_make = ""
    st.session_state.res_thumb = ""

# --- 2. 데이터 및 API 연동 ---
def get_sheets_client():
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        return gspread.authorize(creds)
    except: return None

def load_data():
    client = get_sheets_client()
    if not client: return [], ""
    try:
        spreadsheet = client.open("fastpaper IG like RPA")
        memes = spreadsheet.worksheet("밈").get_all_records()
        archive = spreadsheet.worksheet("rpa").get_all_values()
        
        # H열(기자)과 G열(캡션) 매칭 학습 데이터 생성
        style_samples = [f"[{row[7]}] {row[6]}" for row in archive[1:51] if len(row) > 7 and row[6] and row[7]]
        style_guide = "\n\n".join(style_samples)
        
        return memes, style_guide
    except: return [], ""

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
    except: return "연결 실패"

# --- 3. UI 레이아웃 ---
st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

memes, style_guide = load_data()
meme_context = "\n".join([f"- {m['keyword']}: {m['meaning']}" for m in memes])

col_in, col_out = st.columns([1, 1])

with col_in:
    st.markdown('<div class="section-title">1. 자료 입력</div>', unsafe_allow_html=True)
    raw_text = st.text_area("📄 텍스트 입력 (원본/보도자료)", height=250)
    user_guide = st.text_area("💡 AI 제작 가이드", height=120, placeholder="예: 원하는 내용을 기재하세요, 캡션은 유지해줘, 직접 체험한것처럼 써줘 등")

    st.markdown('---')
    st.markdown('<div class="section-title">2. 작업 실행</div>', unsafe_allow_html=True)
    
    st.markdown('<div class="refresh-btn">', unsafe_allow_html=True)
    if st.button("🔄 결과 새로고침 (Refresh)"):
        reset_results()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    strict_rule = "\n[⚠️ 절대 준수 규칙: 이모티콘(이모지) 사용 절대 금지. 볼드(**)나 # 등 마크다운 형식 금지. 오직 순수 텍스트만 출력할 것.]"

    b_wash = st.button("✨ 문구 워싱")
    b_make = st.button("✍️ 캡션 제작")
    b_thumb = st.button("🖼️ 썸네일 문구 추천")

with col_out:
    st.markdown('<div class="section-title">3. 결과물 확인</div>', unsafe_allow_html=True)
    
    # 기자별 스타일 학습 지침
    style_instruction = f"""
    [말투 학습 데이터]
    {style_guide}
    
    [스타일 지시사항]
    - 위 데이터는 [기자이름] 캡션내용 형식입니다.
    - 사용자가 가이드에 특정 기자(예: 이서준)를 언급하면, 해당 기자의 문체와 감각을 완벽히 복제하세요.
    - 언급이 없다면 패스트페이퍼의 전체적인 세련된 톤을 유지하세요.
    """

    if b_wash:
        if raw_text:
            with st.spinner("워싱 중..."):
                prompt = f"{strict_rule}\n{style_instruction}\n\n[추가 요청]\n{user_guide}\n\n[원본]\n{raw_text}\n\n[지시] 내용을 패스트페이퍼 스타일로 워싱하되, 길이는 가이드의 캡션들처럼 간결하게 유지해."
                st.session_state.res_wash = call_ai(prompt)
        else: st.warning("내용 입력 필요")

    if b_make:
        if raw_text:
            with st.spinner("캡션 제작 중..."):
                prompt = f"{strict_rule}\n{style_instruction}\n\n[추가 요청]\n{user_guide}\n\n[자료]\n{raw_text}\n\n[지시] 인스타그램용 캡션을 제작해줘. 이모지 빼고 가이드와 비슷한 간결한 길이로 작성해."
                st.session_state.res_make = call_ai(prompt)
        else: st.warning("내용 입력 필요")

    if b_thumb:
        if raw_text:
            with st.spinner("썸네일 구상 중..."):
                few_shot_thumb = """
                [썸네일 제작 예시]
                - 차정원 휠라 스니커즈: 차정원의 마카오 여행 속 그 신발, 정체가 궁금합니다
                - 장원영 짐빔 콜라보: 해냈어요. 짐빔이 해냈어요! 원영이 덕분에 세계관 대통합 완료
                - 테라 손흥민 발탁: 큰 거 왔다. 테라랑 쏘니의 만남 COMING SON!
                - 정원규 유니폼브릿지: 환승연애에서 그 티셔츠, 기억하시나요? 정원규 X 유니폼브릿지
                """
                prompt = f"""당신은 패스트페이퍼의 시니어 에디터입니다.
                {few_shot_thumb}
                {style_instruction}
                [가이드]
                - 중요 : 글자 수 20~30자 내외의 임팩트 있는 한 줄로 작성.
                - 중요 : 8개 번호를 매기고 문구 사이 빈 줄 추가.
                - 이모티콘 및 마크다운(볼드 등) 사용 절대 금지.
                - 중요 : 8개 중 3개는 반드시 아래 밈을 섞어 '킹받게' 작성하고, 그 문구 바로 아래에 '(사용한 밈: 밈 이름 - 의미)' 형식으로 설명을 덧붙이세요.
                [실시간 밈 데이터]
                {meme_context}
                [추가 가이드]
                - {strict_rule}
                - {user_guide if user_guide else '없음'}
                [대상 자료]
                {raw_text}
                """
                st.session_state.res_thumb = call_ai(prompt)
        else: st.warning("내용 입력 필요")

    # 결과 출력
    if st.session_state.res_wash:
        st.markdown(f'<div class="content-box"><strong>[문구 워싱 결과]</strong>\n\n{st.session_state.res_wash}</div>', unsafe_allow_html=True)
    if st.session_state.res_make:
        st.markdown(f'<div class="content-box"><strong>[제작된 캡션]</strong>\n\n{st.session_state.res_make}</div>', unsafe_allow_html=True)
    if st.session_state.res_thumb:
        st.markdown(f'<div class="content-box"><strong>[썸네일 문구 제안]</strong>\n\n{st.session_state.res_thumb}</div>', unsafe_allow_html=True)

st.sidebar.caption("© 2026 Fastpaper Washing Bot v2.6")
