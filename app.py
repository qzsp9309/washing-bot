import html
import json
import re
from collections import Counter

import gspread
import requests
import streamlit as st
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="패페 워싱봇 v3.0", page_icon="✍️", layout="wide")

CATEGORIES = ["단체", "라이프", "뷰티", "엔터테인먼트", "테크", "패션", "푸드"]
MODEL = "openai/gpt-4.1-mini"
SHEET_NAME = "fastpaper IG like RPA"
TAB_NAME = "rpa"
MAX_EXAMPLES = 12

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700;800&display=swap');
html, body, [class*="css"] {font-family:'Noto Sans KR',sans-serif;}
.stApp {background:#fff;}
.main-title {font-size:3.2rem;font-weight:800;color:#000;letter-spacing:-.1rem;line-height:1.1;margin-bottom:2rem;}
.content-box {padding:22px;border:1px solid #000;background:#fdfdfd;margin-bottom:16px;white-space:pre-wrap;font-size:1.05rem;line-height:1.7;overflow-wrap:anywhere;}
.stButton>button {background:#000;color:#fff;border-radius:0;border:0;font-weight:700;min-height:3rem;width:100%;}
.stButton>button:hover {background:#333;color:#fff;}
.section-title {font-size:1.5rem;font-weight:700;color:#000;margin-bottom:15px;border-left:5px solid #000;padding-left:10px;}
</style>
""", unsafe_allow_html=True)

for key in ("res_wash", "res_make", "res_thumb", "last_references", "last_category"):
    if key not in st.session_state:
        st.session_state[key] = [] if key == "last_references" else ""


def reset_results():
    for key in ("res_wash", "res_make", "res_thumb", "last_category"):
        st.session_state[key] = ""
    st.session_state.last_references = []


def service_account_info():
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


@st.cache_data(ttl=600, show_spinner=False)
def load_posts():
    # v2.6에서 정상 작동하던 인증 및 스프레드시트 조회 방식 복원
    info = service_account_info()
    creds = Credentials.from_service_account_info(
        info,
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open("fastpaper IG like RPA")
    archive = spreadsheet.worksheet("rpa").get_all_values()

    posts = []
    for sheet_row, row in enumerate(archive[1:], start=2):
        brand = str(row[4]).strip() if len(row) > 4 else ""  # E열
        category = str(row[6]).strip() if len(row) > 6 else ""  # G열
        caption = str(row[7]).strip() if len(row) > 7 else ""  # H열
        if not caption or category not in CATEGORIES:
            continue
        posts.append({"row": sheet_row, "brand": brand, "category": category, "caption": caption})
    return posts


def tokens(text):
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", str(text).lower()))


def select_examples(posts, source_text, selected_category):
    """유사한 브랜드/본문 표현과 최신순을 결합해 소량의 캡션만 AI에 전달."""
    query = source_text.lower()
    query_tokens = tokens(source_text)
    candidates = []
    for index, post in enumerate(posts):
        if selected_category != "자동" and post["category"] != selected_category:
            continue
        brand = post["brand"].strip()
        brand_match = bool(brand and len(brand) >= 2 and brand.lower() in query)
        overlap = len(query_tokens & tokens(post["caption"] + " " + brand))
        recency = (index + 1) / max(len(posts), 1)
        score = (12 if brand_match else 0) + min(overlap, 8) * 2 + recency * 3
        candidates.append((score, index, post))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in candidates[:MAX_EXAMPLES]]


def infer_category(posts, source_text):
    """브랜드 및 텍스트 겹침으로 자동 추천. 확신할 수 없는 경우 최근 데이터 분포 참고."""
    query = source_text.lower()
    query_tokens = tokens(source_text)
    scores = Counter()
    for post in posts[-500:]:
        brand = post["brand"].strip().lower()
        if brand and len(brand) >= 2 and brand in query:
            scores[post["category"]] += 12
        scores[post["category"]] += min(len(query_tokens & tokens(post["caption"])), 5)
    return scores.most_common(1)[0][0] if scores and scores.most_common(1)[0][1] > 0 else "라이프"


def call_ai(prompt):
    try:
        key = st.secrets["openrouter_api_key"]
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "당신은 FASTPAPER의 한국어 SNS 카피 에디터입니다. 자료의 사실관계를 지키고, 참고 캡션의 문체만 반영하세요."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.75,
                "max_tokens": 1200,
            },
            timeout=90,
        )
        if not response.ok:
            try:
                detail = response.json().get("error", {}).get("message", "알 수 없는 API 오류")
            except (ValueError, AttributeError):
                detail = "응답 본문을 확인할 수 없습니다."
            st.error(f"OpenRouter 오류 (HTTP {response.status_code}): {detail}")
            return ""
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not content:
            st.error("AI가 빈 응답을 반환했습니다.")
            return ""
        return content.strip()
    except requests.Timeout:
        st.error("AI 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    except KeyError as exc:
        st.error(f"설정 또는 API 응답 항목이 없습니다: {exc}")
    except Exception as exc:
        st.error(f"AI 연결 오류: {type(exc).__name__}: {exc}")
    return ""


def make_prompt(task, source, guide, category, examples):
    examples_text = "\n\n".join(
        f"[참고 {i}] 카테고리: {p['category']} / 브랜드: {p['brand'] or '미기재'}\n{p['caption'][:900]}"
        for i, p in enumerate(examples, 1)
    )
    instructions = {
        "wash": "원문에 있는 사실과 고유명사는 유지하고, 표현만 FASTPAPER의 자연스럽고 간결한 인스타그램 문체로 다듬으세요. 근거 없는 경험담, 평가, 사실을 추가하지 마세요.",
        "make": "제공된 자료로 FASTPAPER 인스타그램 캡션 1개를 새로 작성하세요. 핵심 정보가 빠지지 않도록 하되 참고 캡션과 유사한 호흡과 분량으로 작성하세요. 직접 경험하지 않은 내용을 체험담처럼 쓰지 마세요.",
        "thumb": "콘텐츠의 핵심을 살린 썸네일 카피를 서로 다른 각도로 8개 제안하세요. 각 문구는 가급적 20~30자 내외로 간결하게 작성하고, 1~8 번호를 붙여 빈 줄로 구분하세요. 밈을 억지로 사용하지 마세요.",
    }
    return f"""[작업] {instructions[task]}
[콘텐츠 카테고리] {category}
[참고 캡션의 사용 원칙]
- 아래 캡션은 문체, 문장 길이, 톤을 참고하기 위한 예시입니다.
- 참고 캡션의 브랜드, 사실, 행사, 인물 정보를 현재 글에 섞지 마세요.
- 특정 표현을 그대로 복사하지 마세요.
- 결과에는 이모지, 해시태그, 볼드(**) 등의 마크다운을 쓰지 마세요.
- 추가 요청이 있으면 사실관계를 해치지 않는 범위에서 반영하세요.

[과거 FASTPAPER 게시글 참고]
{examples_text if examples_text else '참고 게시글 없음. 제공된 자료에 근거하여 작성하세요.'}

[추가 요청]
{guide or '없음'}

[현재 자료]
{source}
"""


st.markdown('<div class="main-title">FASTPAPER<br>WASHING BOT</div>', unsafe_allow_html=True)

try:
    posts = load_posts()
    data_error = ""
except Exception as exc:
    posts = []
    data_error = f"{type(exc).__name__}: {exc}"

status_col, refresh_col = st.columns([4, 1])
with status_col:
    if data_error:
        st.warning(f"구글 시트 연결 오류: {data_error}")
    else:
        st.caption(f"rpa 게시글 {len(posts):,}개 연결됨 · E열 브랜드 / G열 카테고리 / H열 캡션 · 10분 캐싱")
with refresh_col:
    if st.button("🔄 게시글 새로고침", key="refresh_sheet"):
        load_posts.clear()
        st.rerun()

col_in, col_out = st.columns([1, 1], gap="large")
with col_in:
    st.markdown('<div class="section-title">1. 자료 입력</div>', unsafe_allow_html=True)
    raw_text = st.text_area("📄 텍스트 입력 (원본/보도자료)", height=250)
    user_guide = st.text_area("💡 AI 제작 가이드", height=120, placeholder="예: 제품 특징을 강조해줘, 캡션은 짧게 써줘")
    category_choice = st.selectbox("📂 카테고리", ["자동"] + CATEGORIES, help="자동은 입력한 글과 과거 캡션을 비교해 카테고리를 추천합니다.")
    if raw_text.strip() and posts:
        effective_category = infer_category(posts, raw_text) if category_choice == "자동" else category_choice
        st.caption(f"적용 카테고리: {effective_category}" + (" (자동 추천)" if category_choice == "자동" else ""))
    else:
        effective_category = category_choice if category_choice != "자동" else "라이프"
    st.divider()
    st.markdown('<div class="section-title">2. 작업 실행</div>', unsafe_allow_html=True)
    if st.button("🔄 결과 초기화"):
        reset_results()
        st.rerun()
    b_wash = st.button("✨ 문구 워싱")
    b_make = st.button("✍️ 캡션 제작")
    b_thumb = st.button("🖼️ 썸네일 문구 추천")

with col_out:
    st.markdown('<div class="section-title">3. 결과물 확인</div>', unsafe_allow_html=True)
    task = "wash" if b_wash else "make" if b_make else "thumb" if b_thumb else None
    if task:
        if not raw_text.strip():
            st.warning("내용을 입력해 주세요.")
        else:
            selected = select_examples(posts, raw_text, effective_category)
            # 선택 카테고리에 해당하는 게시글이 없으면 최근 전체 게시글로 보완
            if not selected and posts:
                selected = select_examples(posts, raw_text, "자동")
            prompt = make_prompt(task, raw_text, user_guide, effective_category, selected)
            with st.spinner("패스트페이퍼 스타일로 작성 중..."):
                result = call_ai(prompt)
            if result:
                st.session_state[{"wash": "res_wash", "make": "res_make", "thumb": "res_thumb"}[task]] = result
                st.session_state.last_references = selected
                st.session_state.last_category = effective_category

    for title, key in (("문구 워싱 결과", "res_wash"), ("제작된 캡션", "res_make"), ("썸네일 문구 제안", "res_thumb")):
        if st.session_state[key]:
            safe_title = html.escape(title)
            safe_text = html.escape(st.session_state[key])
            st.markdown(f'<div class="content-box"><strong>[{safe_title}]</strong>\n\n{safe_text}</div>', unsafe_allow_html=True)
            st.code(st.session_state[key], language=None, wrap_lines=True)

    if st.session_state.last_references:
        with st.expander(f"📚 마지막 작업 참고 게시글 ({len(st.session_state.last_references)}개 · {st.session_state.last_category})"):
            for p in st.session_state.last_references:
                st.caption(f"rpa {p['row']}행 · {p['category']} · {p['brand'] or '브랜드 미기재'}")
                st.text(p["caption"][:500])
                st.divider()

st.sidebar.caption("© 2026 Fastpaper Washing Bot v3.0")
