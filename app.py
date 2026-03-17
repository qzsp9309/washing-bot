import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
import base64
from docx import Document
import io

# --- 1. 기본 설정 및 디자인 (매거진 톤) ---
st.set_page_config(page_title="패페 워싱봇 v2.0", page_icon="🤖", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .stApp { background-color: #ffffff; }
    .main-title { font-size: 3.2rem; font-weight: 800; color: #000; letter-spacing: -0.1rem; line-height: 1.1; margin-bottom: 2rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; border-bottom: 2px solid #000; }
    .stTabs [data-baseweb="tab"] { font-size: 1.1rem; font-weight: 700; color: #999; padding: 10px 0; }
    .stTabs [aria-selected="true"] { color: #000 !important; border-bottom-color: #000 !important; }
    .content-box { padding: 25px; border-radius: 0px; border: 1px solid #000; background-color: #fdfdfd; margin-bottom: 20px; }
    .stButton>button { background-color: #000; color: #fff; border-radius: 0px; border: none; font-weight: 700; height: 3.5rem; transition: 0.3s; }
    .stButton>button:hover { background-color: #333; color: #fff; border: none; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 인증 및 데이터 연동 함수 ---
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
    if not client: return [], "스타일 가이드를 불러올 수 없습니다."
    try:
        spreadsheet = client.open("fastpaper IG like RPA")
        # n8n 수집 밈 탭
        memes = spreadsheet.worksheet("trending_memes").get_all_records()
        # 말투 학습 (요청 탭 D열 최근 10개)
        archive = spreadsheet.worksheet("요청").get_all_values()
        style = "\n\n".join([row[3] for row in archive[-11:] if len(row) > 3])
        return memes, style
    except:
        return [], "감각적인 매거진 톤을 유지하세요."

def call_ai(prompt, image_b64=None):
    api_key = st.secrets["openrouter_api_key"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    content = [{"type": "text", "text": prompt}]
    if image_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
        
    payload = {
        "model": "google/gemini-2.0-flash-001", # 이미지 분석 효율 최상 모델
        "messages": [{"role": "user", "content": content}]
    }
    
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        return res.json()['choices'][0]['message']['content']
    except:
        return "AI 연결 실패. 잠시 후 다시 시도하세요."

def parse_document(file):
    if file.name.endswith('.txt'):
        return file.read().decode('utf-8')
    elif file.name.endswith('.docx'):
        doc = Document(io.BytesIO(file.read()))
        return "\n".join([p.text for p in doc.paragraphs])
    return ""

# --- 3. 사이트 레이아웃 구성 ---
st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

# 지식 동기화
memes, style_guide = load_data()
meme_context = "\n".join([f"- {m['keyword']}: {m['meaning']}" for m in memes])

# 4개 메인 탭
tab1, tab2, tab3, tab4 = st.tabs(["📂 자료 업로드", "✨ 문구 워싱", "✍️ 문구 제작", "🖼️ 썸네일 제안"])

# [탭 1: 자료 업로드]
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🖼️ 이미지")
        img_file = st.file_uploader("이미지를 업로드하세요", type=['jpg', 'png', 'jpeg'])
        if img_file:
            st.image(img_file, use_container_width=True)
            st.session_state['img_b64'] = base64.b64encode(img_file.getvalue()).decode('utf-8')
    with col2:
        st.subheader("📄 텍스트/보도자료")
        doc_file = st.file_uploader("txt 또는 docx 파일", type=['txt', 'docx'])
        if doc_file:
            content = parse_document(doc_file)
            st.session_state['ref_text'] = content
            st.success("자료 업로드 성공")
            st.text_area("내용 확인", content, height=200)

# [탭 2: 문구 워싱]
with tab2:
    st.subheader("패페 스타일 워싱")
    wash_input = st.text_area("워싱할 문구 입력", st.session_state.get('ref_text', ''), height=150)
    if st.button("워싱 실행", use_container_width=True):
        with st.spinner("에디터가 원고를 다듬고 있습니다..."):
            prompt = f"당신은 베테랑 에디터입니다. 아래 원문을 패스트페이퍼의 세련된 말투로 워싱하세요. 이미지를 참고하여 시각적 묘사를 더해도 좋습니다.\n\n[말투 가이드]\n{style_guide}\n\n[원문]\n{wash_input}"
            res = call_ai(prompt, st.session_state.get('img_b64'))
            st.markdown(f'<div class="content-box"><strong>[원본]</strong><br>{wash_input}<br><br><strong>[제안]</strong><br>{res}</div>', unsafe_allow_html=True)

# [탭 3: 문구 제작]
with tab3:
    st.subheader("신규 캡션 생성")
    make_input = st.text_area("참고할 팩트 데이터", st.session_state.get('ref_text', ''), height=200)
    if st.button("제작 시작", use_container_width=True):
        with st.spinner("캡션 제작 중..."):
            prompt = f"이미지와 자료를 분석하여 인스타그램용 캡션을 제작하세요. 감각적인 톤앤매너를 유지하세요.\n\n[말투 가이드]\n{style_guide}\n\n[참고자료]\n{make_input}"
            res = call_ai(prompt, st.session_state.get('img_b64'))
            st.markdown(f'<div class="content-box">{res}</div>', unsafe_allow_html=True)

# [탭 4: 썸네일 제안]
with tab4:
    st.subheader("썸네일 문구 5선")
    if st.button("제안 받기", use_container_width=True):
        with st.spinner("아이디어를 짜내고 있습니다..."):
            prompt = f"이미지와 자료를 보고 썸네일 문구 5개를 제안하세요. 한 줄 구성, 이모티콘 금지.\n5개 중 최소 1개는 반드시 다음 [실시간 밈]을 활용하세요.\n\n[오늘의 밈]\n{meme_context}\n\n[내용]\n{st.session_state.get('ref_text', '')}"
            res = call_ai(prompt, st.session_state.get('img_b64'))
            st.markdown(f'<div class="content-box">{res}</div>', unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 Fastpaper Washing Bot")