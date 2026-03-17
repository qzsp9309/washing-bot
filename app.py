import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
import base64
from docx import Document
import io

# --- 1. 기본 설정 및 디자인 ---
st.set_page_config(page_title="패페 워싱봇 v2.0", page_icon="🤖", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
    .stApp { background-color: #ffffff; }
    .main-title { font-size: 3.2rem; font-weight: 800; color: #000; letter-spacing: -0.1rem; line-height: 1.1; margin-bottom: 2rem; }
    .content-box { padding: 25px; border-radius: 0px; border: 1px solid #000; background-color: #fdfdfd; margin-bottom: 20px; white-space: pre-wrap; }
    .stButton>button { background-color: #000; color: #fff; border-radius: 0px; border: none; font-weight: 700; height: 3.5rem; transition: 0.3s; width: 100%; margin-bottom: 10px; }
    .stButton>button:hover { background-color: #333; color: #fff; border: none; }
    .section-title { font-size: 1.5rem; font-weight: 700; color: #000; margin-bottom: 15px; border-left: 5px solid #000; padding-left: 10px; }
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
        memes = spreadsheet.worksheet("trending_memes").get_all_records()
        archive = spreadsheet.worksheet("요청").get_all_values()
        style = "\n\n".join([row[3] for row in archive[-11:] if len(row) > 3])
        return memes, style
    except:
        return [], "감각적인 매거진 톤을 유지하세요."

def call_ai(prompt, images_b64=None):
    if "openrouter_api_key" not in st.secrets:
        return "오픈라우터 API 키가 설정되지 않았습니다."
    
    api_key = st.secrets["openrouter_api_key"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    content = [{"type": "text", "text": prompt}]
    
    # 다중 이미지 대응
    if images_b64:
        for img_b64 in images_b64:
            content.append({
                "type": "image_url", 
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        
    payload = {
        "model": "google/gemini-2.0-flash-001", 
        "messages": [{"role": "user", "content": content}]
    }
    
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        res_json = res.json()
        if "error" in res_json:
            return f"AI 에러 발생: {res_json['error'].get('message', '알 수 없는 오류')}"
        return res_json['choices'][0]['message']['content']
    except Exception as e:
        return f"AI 호출 실패: {e}"

# --- 3. 사이트 레이아웃 구성 ---
st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

# 지식 동기화
memes, style_guide = load_data()
meme_context = "\n".join([f"- {m['keyword']}: {m['meaning']}" for m in memes])

# 사이트 구성 (단일 페이지 형태)
col_input, col_output = st.columns([1, 1])

with col_input:
    st.markdown('<div class="section-title">1. 자료 입력</div>', unsafe_allow_html=True)
    
    # 이미지 다중 업로드 (개수 제한 없음)
    img_files = st.file_uploader("🖼️ 이미지들을 업로드하세요 (여러 장 가능)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)
    images_b64 = []
    if img_files:
        cols = st.columns(min(len(img_files), 4)) # 최대 4열로 미리보기
        for i, img_file in enumerate(img_files):
            cols[i % 4].image(img_file, use_container_width=True)
            images_b64.append(base64.b64encode(img_file.getvalue()).decode('utf-8'))

    # 텍스트 직접 입력 방식
    raw_text = st.text_area("📄 원본 문구 또는 보도자료 내용", height=200, placeholder="여기에 워싱할 문구나 참고할 보도자료 내용을 넣어주세요.")

    # 추가 제작 가이드 (동준 님 요청 5번)
    user_guide = st.text_input("💡 추가 제작 가이드 (옵션)", placeholder="예: '친환경' 키워드 꼭 포함해줘, 가격 정보를 강조해줘 등")

    st.markdown('---')
    st.markdown('<div class="section-title">2. 작업 실행</div>', unsafe_allow_html=True)
    
    # AI 공통 가이드 (동준 님 요청 6번: 볼드/크기조정 금지, 이모티콘 금지)
    ai_strict_rule = "\n[절대 준수 규칙: 볼드(**)나 글자 크기 조정(#) 등 마크다운 형식을 사용하지 말 것. 이모티콘은 절대 사용하지 말 것.]"

    # 버튼 3종 세트 (동준 님 요청 3번)
    btn_wash = st.button("✨ 문구 워싱 실행")
    btn_make = st.button("✍️ 신규 캡션 제작")
    btn_thumb = st.button("🖼️ 썸네일 제안 받기")

with col_output:
    st.markdown('<div class="section-title">3. 결과물 확인</div>', unsafe_allow_html=True)
    
    # 1) 문구 워싱 실행
    if btn_wash:
        if not raw_text:
            st.error("원본 문구를 먼저 입력해주세요.")
        else:
            with st.spinner("패페 스타일로 리터칭 중..."):
                prompt = f"""당신은 베테랑 에디터입니다. 아래 원문을 패스트페이퍼의 세련된 말투로 워싱하세요. 
                {ai_strict_rule}
                
                [말투 가이드]
                {style_guide}
                
                [추가 요청사항]
                {user_guide if user_guide else '없음'}
                
                [원본 문구]
                {raw_text}"""
                res = call_ai(prompt, images_b64)
                st.markdown(f"**[워싱 결과]**")
                st.markdown(f'<div class="content-box">{res}</div>', unsafe_allow_html=True)

    # 2) 신규 캡션 제작 실행
    if btn_make:
        if not raw_text:
            st.error("참고할 자료를 입력해주세요.")
        else:
            with st.spinner("인스타그램용 캡션 제작 중..."):
                prompt = f"""이미지와 자료를 분석하여 인스타그램용 캡션을 제작하세요. 
                {ai_strict_rule}
                
                [말투 가이드]
                {style_guide}
                
                [추가 요청사항]
                {user_guide if user_guide else '없음'}
                
                [참고자료]
                {raw_text}"""
                res = call_ai(prompt, images_b64)
                st.markdown(f"**[제작된 캡션]**")
                st.markdown(f'<div class="content-box">{res}</div>', unsafe_allow_html=True)

    # 3) 썸네일 제안 실행 (동준 님 요청 4번: 줄 구분 강화)
    if btn_thumb:
        with st.spinner("썸네일 문구 구상 중..."):
            prompt = f"""이미지와 자료를 보고 썸네일 문구 5개를 제안하세요. 
            - 각 문구는 한 줄로 작성하고 문구 사이에 빈 줄을 넣어 가독성을 높이세요.
            - {ai_strict_rule}
            - 5개 중 최소 1개는 반드시 다음 [실시간 밈]을 활용하세요.
            
            [실시간 밈]
            {meme_context}
            
            [추가 요청사항]
            {user_guide if user_guide else '없음'}
            
            [참고내용]
            {raw_text}"""
            res = call_ai(prompt, images_b64)
            st.markdown(f"**[썸네일 제안 5선]**")
            st.markdown(f'<div class="content-box">{res}</div>', unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 Fastpaper Washing Bot")
