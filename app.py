import html
import json
import re
import io
import shutil
import subprocess
from collections import Counter

import gspread
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from docx import Document
import fitz

st.set_page_config(page_title="패페 워싱봇 v3.1", page_icon="✍️", layout="wide")

CATEGORIES = ["단체", "라이프", "뷰티", "엔터테인먼트", "테크", "패션", "푸드"]
MODEL = "openai/gpt-4.1-mini"
SHEET_NAME = "★ fastpaper IG like RPA"
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
    # v2.6에서 사용하던 인증/시트 열기 방식 그대로 유지
    raw = st.secrets["gcp_service_account"]
    info = json.loads(raw) if isinstance(raw, str) else dict(raw)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    client = gspread.authorize(creds)

    # 별도 spreadsheet_id Secret은 요구하지 않음.
    # 기존 v2.6처럼 문서명으로 열고, 그 안의 rpa 탭을 선택.
    spreadsheet = client.open("★ fastpaper IG like RPA")
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


def diagnose_sheet_access():
    """연결 오류 시에만 실행. 문서명과 서비스 계정 접근 권한을 진단."""
    raw = st.secrets["gcp_service_account"]
    info = json.loads(raw) if isinstance(raw, str) else dict(raw)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scope)
    client = gspread.authorize(creds)
    accessible = client.list_spreadsheet_files()
    names = [x.get("name", "") for x in accessible]
    return info.get("client_email", ""), names


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


def extract_attachment(uploaded):
    """PDF / DOCX / legacy DOC text extraction; no file is sent anywhere until AI action."""
    suffix = uploaded.name.rsplit(".", 1)[-1].lower()
    data = uploaded.getvalue()
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("파일당 20MB 이하만 지원합니다.")
    if suffix == "pdf":
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if len(pdf) > 80:
                raise ValueError("PDF는 최대 80페이지까지 지원합니다.")
            content = "\n".join(page.get_text(sort=True) for page in pdf)
    elif suffix == "docx":
        document = Document(io.BytesIO(data))
        blocks = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                blocks.append(" | ".join(cell.text for cell in row.cells))
        content = "\n".join(blocks)
    elif suffix == "doc":
        if not shutil.which("antiword"):
            raise ValueError("구형 .doc 파일은 현재 서버에서 지원하지 않습니다. Word에서 .docx로 저장해 업로드해 주세요.")
        result = subprocess.run(["antiword", "-"], input=data, capture_output=True, timeout=20)
        if result.returncode != 0:
            raise ValueError(".doc 파일을 읽지 못했습니다. .docx로 변환해 주세요.")
        content = result.stdout.decode("utf-8", errors="replace")
    else:
        raise ValueError("PDF 또는 Word 파일만 지원합니다.")
    if not content.strip():
        raise ValueError("추출 가능한 텍스트가 없습니다. 스캔 이미지 PDF는 텍스트 인식이 필요합니다.")
    return content.strip()


def combine_source(raw_text, attachments):
    sections = []
    if raw_text.strip():
        sections.append("[직접 입력한 자료]\n" + raw_text.strip())
    for name, text in attachments:
        sections.append(f"[첨부파일: {name}]\n{text}")
    return "\n\n".join(sections)


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
                "temperature": 0.55,
                "max_tokens": 1800,
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
    common = """[공통 편집 원칙]
- FASTPAPER의 실제 기자가 독자에게 소식을 전하는 자연스러운 매거진 에디토리얼 톤을 사용하세요.
- 제공 자료의 사실, 인물명, 브랜드명, 캠페인명, 필수 제품명, 제품별 특징을 정확히 유지하세요.
- 광고 가이드의 필수 조건을 누락하지 마세요. 근거 없는 특징, 평가, 체험, 가격, 출시일을 만들어내지 마세요.
- 브랜드 보도자료 문장을 그대로 늘이거나 홍보성 수식어를 추가하지 마세요.
- '자랑합니다', '완벽한', '스타일리시한', '지금 만나보세요', '스타일을 완성해보세요' 등 상투적 판촉 표현을 가급적 피하세요.
- 비슷한 정보와 표현은 반복하지 말고, 문장별로 정보의 역할을 나누세요.
- 과거 참고 캡션은 문장 리듬, 정보 배치, 문단 호흡을 학습하는 데만 사용하세요. 다른 게시글의 사실을 현재 글에 섞거나 문장을 복제하지 마세요.
- 추가 요청은 위 사실관계 및 필수 정보 조건을 지키는 범위에서 반영하세요.
- 자료에 '필수', '반드시', '유의' 등 조건이 있으면 먼저 찾아 반영하세요.
- 최종 출력 전에 필수 고유명사/제품명 누락, 광고 문구 과다, 사실 추가, 중복, 문단 흐름을 자체 점검하고 완성본만 출력하세요.
- 결과물에 마크다운 볼드(**)나 설명문, 불필요한 이모지를 넣지 마세요."""
    task_rules = {
        "wash": """[문구 워싱]
- 원문의 정보와 핵심 메시지는 유지하되 어색한 문장, 과한 홍보 표현, 중복을 줄여 주세요.
- 이미 명시된 #광고, 해시태그, 에디터/이미지 출처는 임의로 삭제하거나 변경하지 마세요.
- 원문에 없는 에디터명, 이미지 계정, 태그를 새로 만들지 마세요.
- 원문의 구조를 존중하면서 자연스러운 문단 구성을 만드세요.""",
        "make": """[캡션 제작]
- 핵심 소식을 소개하는 1문단 → 인물·제품·특징을 연결하는 2문단 → 독자 관점의 자연스러운 마무리 3문단을 기본으로 하되, 내용에 따라 문단 수를 조절하세요.
- 첫 문단에서 누가 무엇을 공개/발표/선보였는지 명확히 전달하세요. 계절감만으로 시작하는 막연한 광고식 도입을 피하세요.
- 제품별 특징은 해당 인물과 제품명에 정확히 연결하세요. 모든 제품 특징을 한 문장에 몰아넣지 마세요.
- '선보입니다', '완성했는데요', '확인해 보세요' 같은 자연스러운 기사형 종결을 문맥에 맞게 사용하되 같은 어미를 과하게 반복하지 마세요.
- 광고 콘텐츠임이 자료에 명시되어 있으면 첫 줄에 '#광고'를 표시하세요. 썸네일 문구가 제공되지 않았다면 임의로 정하거나 '첫 문장은 썸네일 문구' 같은 작업 지침을 본문에 출력하지 마세요.
- 에디터명·이미지 출처는 자료에 명시된 경우에만 기재하세요. 담당자를 추측하거나 임의로 생성하지 마세요.
- 해시태그는 가이드가 제공되면 우선 반영하고, 없으면 핵심 브랜드·인물·주제 위주로 적은 수만 제안하세요. 필요하면 '댓글태그)'를 별도 구분하세요.
- 해시태그를 제외한 본문은 과도하게 길게 쓰지 마세요.""",
        "thumb": """[썸네일 문구 추천]
- 독자가 클릭할 만한 사실 기반의 서로 다른 앵글 8개를 제안하세요.
- 문구당 가급적 20~30자 내외로 간결하게 작성하고 1~8 번호를 붙여 빈 줄로 구분하세요.
- 근거 없는 과장, 확인되지 않은 사실, 억지 밈은 사용하지 마세요.
- 썸네일 문구만 출력하고 해시태그나 에디터 정보를 붙이지 마세요.""",
    }
    return f"""{common}

{task_rules[task]}

[콘텐츠 카테고리] {category}

[과거 FASTPAPER 게시글 참고 — 사실 정보로 사용 금지]
{examples_text if examples_text else '참고 게시글 없음. 현재 자료에 근거하여 작성하세요.'}

[사용자 추가 가이드]
{guide or '없음'}

[현재 자료 및 첨부 문서 — 사실 정보의 유일한 근거]
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
        if "SpreadsheetNotFound" in data_error:
            st.info("기존 v2.6 인증·시트 연결 코드를 그대로 사용 중입니다. 이 오류는 현재 서비스 계정에서 해당 이름의 문서를 찾지 못한다는 뜻입니다. 아래 진단 버튼으로 권한/문서명을 확인해 주세요.")
            if st.button("🔎 구글 시트 연결 진단", key="diagnose_sheet"):
                try:
                    email, names = diagnose_sheet_access()
                    st.write(f"현재 서비스 계정: `{email}`")
                    st.write(f"접근 가능한 스프레드시트 수: {len(names)}")
                    st.write("문서 이름 (최대 20개):", names[:20])
                    st.caption("기존 문서가 목록에 없으면 해당 서비스 계정 이메일에 구글 시트 공유 권한을 부여해야 합니다. 목록에 다른 이름으로 있으면 SHEET_NAME을 그 이름으로 변경하세요.")
                except Exception as diag_exc:
                    st.error(f"진단 실패: {type(diag_exc).__name__}: {diag_exc}")
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
    uploaded_files = st.file_uploader("📎 PDF / Word 파일 첨부", type=["pdf", "docx", "doc"], accept_multiple_files=True, help="파일당 20MB, PDF 최대 80페이지. 이미지로만 된 스캔 PDF는 텍스트를 추출할 수 없습니다.")
    attachments = []
    for uploaded in uploaded_files or []:
        try:
            extracted = extract_attachment(uploaded)
            attachments.append((uploaded.name, extracted))
            st.caption(f"✓ {uploaded.name} · 텍스트 {len(extracted):,}자 추출")
        except Exception as exc:
            st.warning(f"{uploaded.name}: {exc}")
    combined_source = combine_source(raw_text, attachments)
    if len(combined_source) > 60000:
        st.warning("자료가 60,000자를 초과했습니다. API 요청 한도를 고려해 일부 내용을 줄여 주세요.")
    user_guide = st.text_area("💡 AI 제작 가이드", height=120, placeholder="예: 제품 특징을 강조해줘, 캡션은 짧게 써줘")
    category_choice = st.selectbox("📂 카테고리", ["자동"] + CATEGORIES, help="자동은 입력한 글과 과거 캡션을 비교해 카테고리를 추천합니다.")
    if combined_source.strip() and posts:
        effective_category = infer_category(posts, combined_source) if category_choice == "자동" else category_choice
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
        if not combined_source.strip():
            st.warning("내용을 입력해 주세요.")
        elif len(combined_source) > 60000:
            st.warning("자료를 60,000자 이하로 줄여 주세요.")
        else:
            selected = select_examples(posts, combined_source, effective_category)
            # 선택 카테고리에 해당하는 게시글이 없으면 최근 전체 게시글로 보완
            if not selected and posts:
                selected = select_examples(posts, raw_text, "자동")
            prompt = make_prompt(task, combined_source, user_guide, effective_category, selected)
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

st.sidebar.caption("© 2026 Fastpaper Washing Bot v3.1")
