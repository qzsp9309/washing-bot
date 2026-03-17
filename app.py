import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
from docx import Document
import io

# --- 1. 기본 설정 및 디자인 ---
st.set_page_config(page_title="패페 워싱봇 v2.2", page_icon="✍️", layout="wide")

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
        memes = spreadsheet.worksheet("trending_memes").get_all_records()
        archive = spreadsheet.worksheet("요청").get_all_values()
        style = "\n\n".join([row[3] for row in archive[-11:] if len(row) > 3])
        return memes, style
    except:
        return [], "매거진 톤 가이드를 불러올 수 없습니다."

def call_ai(prompt):
    if "openrouter_api_key" not in st.secrets:
        return "API 키가 설정되지 않았습니다."
    
    api_key = st.secrets["openrouter_api_key"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    payload = {
        "model": "openrouter/free", 
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        res_json = res.json()
        if "error" in res_json:
            return f"오픈라우터 에러: {res_json['error'].get('message', '한도 초과')}"
        return res_json['choices'][0]['message']['content']
    except Exception as e:
        return f"연결 실패: {e}"

# --- 3. UI 레이아웃 ---
st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

memes, style_guide = load_data()
meme_context = "\n".join([f"- {m['keyword']}: {m['meaning']}" for m in memes])

col_in, col_out = st.columns([1, 1])

with col_in:
    st.markdown('<div class="section-title">1. 자료 입력</div>', unsafe_allow_html=True)
    raw_text = st.text_area("📄 텍스트 입력 (원본/보도자료)", height=350, placeholder="여기에 내용을 붙여넣으세요.")
    user_guide = st.text_input("💡 AI 제작 가이드", placeholder="예: '신제품 강조', '가격 정보 포함'")

    st.markdown('---')
    st.markdown('<div class="section-title">2. 작업 실행</div>', unsafe_allow_html=True)
    
    strict_rule = "\n[⚠️ 절대 준수 규칙: 이모티콘 사용 금지. 볼드(**)나 # 등 마크다운 형식 금지. 오직 텍스트만 출력할 것.]"

    b_wash = st.button("✨ 문구 워싱")
    b_make = st.button("✍️ 캡션 제작")
    b_thumb = st.button("🖼️ 썸네일 추천")

with col_out:
    st.markdown('<div class="section-title">3. 결과물 확인</div>', unsafe_allow_html=True)
    
    if b_wash:
        if raw_text:
            with st.spinner("패페 스타일 리터칭 중..."):
                prompt = f"{strict_rule}\n\n[말투 가이드]\n{style_guide}\n\n[추가 요청]\n{user_guide}\n\n[원본]\n{raw_text}\n\n패스트페이퍼 스타일로 워싱해줘."
                res = call_ai(prompt)
                st.markdown(f'<div class="content-box"><strong>[워싱 결과]</strong>\n\n{res}</div>', unsafe_allow_html=True)
        else:
            st.warning("내용을 입력해주세요.")

    if b_make:
        if raw_text:
            with st.spinner("인스타그램 캡션 제작 중..."):
                prompt = f"{strict_rule}\n\n[말투 가이드]\n{style_guide}\n\n[추가 요청]\n{user_guide}\n\n[자료]\n{raw_text}\n\n인스타그램용 캡션을 제작해줘."
                res = call_ai(prompt)
                st.markdown(f'<div class="content-box"><strong>[제작된 캡션]</strong>\n\n{res}</div>', unsafe_allow_html=True)
        else:
            st.warning("내용을 입력해주세요.")

    if b_thumb:
        if raw_text:
            with st.spinner("패스트페이퍼급 썸네일 구상 중..."):
                few_shot = """
                [썸네일 제작 예시]
                - 차정원 휠라 스니커즈: 차정원의 마카오 여행 속 그 신발, 정체가 궁금합니다 
                - 장원영 짐빔 콜라보: 해냈어요. 짐빔이 해냈어요! 원영이 덕분에 세계관 대통합 완료
                - 테라 손흥민 발탁: 큰 거 왔다. 테라랑 쏘니의 만남 COMING SON!
                - 정원규 유니폼브릿지: 환승연애에서 그 티셔츠, 기억하시나요? 정원규 X 유니폼브릿지
                """
                prompt = f"""당신은 패스트페이퍼의 시니어 에디터입니다.
                {few_shot}
                [가이드]
                - 글자 수 20~30자 내외의 임팩트 있는 한 줄로 작성.
                - 5개 번호를 매기고 문구 사이 빈 줄 추가.
                - 최소 1개는 실시간 밈 활용: {meme_context}
                - {strict_rule}
                [추가 요청] {user_guide}
                [자료] {raw_text}"""
                res = call_ai(prompt)
                st.markdown(f'<div class="content-box"><strong>[썸네일 제안 5선]</strong>\n\n{res}</div>', unsafe_allow_html=True)
        else:
            st.warning("내용을 입력해주세요.")

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 Fastpaper Washing Bot")
