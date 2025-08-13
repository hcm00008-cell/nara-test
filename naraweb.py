# naraweb.py
import os
import io
import time
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

# Optional: load local .env for dev (only if you use .env locally)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# AgGrid (optional, 권장)
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False

# ----------------- 설정 -----------------
SERVICE_KEY = os.getenv("NARA_SERVICE_KEY")
if not SERVICE_KEY:
    # 배포 환경에서 반드시 Secrets에 NARA_SERVICE_KEY 등록 필요
    st.warning("환경변수 NARA_SERVICE_KEY가 설정되어 있지 않습니다. 배포 환경의 Secrets에 등록하세요.")
API_URL = 'http://apis.data.go.kr/1230000/ao/CntrctInfoService/getCntrctInfoListServcPPSSrch'
MAX_API_ROWS = 999

# Debug 제어: 배포시에는 반드시 false
DEBUG = os.getenv("NARA_DEBUG", "false").lower() in ("1", "true", "yes")

# 화면 표시용 컬럼 매핑 (필요 시 확장)
display_columns_map = {
    'untyCntrctNo': '통합계약번호',
    'bsnsDivNm': '업무구분명',
    'cntrctNm': '계약명',
    'cntrctCnclsDate': '계약체결일자',
    'totCntrctAmt': '총계약금액',
    'thtmCntrctAmt': '금차계약금액',
    'cntrctInsttNm': '계약기관명',
    'dminsttList': '수요기관목록',
    'corpList': '업체목록',
    'wbgnDate': '착수일자',
    'ttalScmpltDate': '총완수일자',
}
display_column_names = list(display_columns_map.values())

# 원본 금액 컬럼들 변수 (사용 중이던 변수명 유지)
DOWNLOAD_AMOUNT_ORIGINAL_COLS = ['totCntrctAmt', 'thtmCntrctAmt']

# 소관기관 매핑 (이미 정해진 코드)
INSTITUTION_TYPES = {
    "국가기관": "01",
    "지방자치단체": "02",
    "교육기관": "03",
    "정부투자기관": "05",
    "임의기관": "07",
    "공기업": "51",
    "준정부기관": "52",
    "기타공공기관": "53",
    "지방공기업": "71",
    "기타기관": "72",
}

# ----------------- Streamlit 페이지 설정 -----------------
st.set_page_config(page_title="나라장터 계약 내역 조회", layout="wide")
st.title("🏛️ 나라장터 용역 계약 내역 조회")

# 좌측 상단 배지 (개발자 표시)
st.markdown(
    """
    <div style="
        position: fixed;
        top: 8px;
        left: 8px;
        background: rgba(255,255,255,0.90);
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 20pt;
        font-weight: 700;
        color: #222;
        z-index: 9999;
        box-shadow: 0 2px 6px rgba(0,0,0,0.12);
    ">
        개발: 루이튼 (즐거운베이글1202)
    </div>
    """,
    unsafe_allow_html=True
)

# ----------------- Session state 초기화 -----------------
if 'data_df' not in st.session_state:
    st.session_state.data_df = pd.DataFrame()
if 'filtered_data_df' not in st.session_state:
    st.session_state.filtered_data_df = pd.DataFrame()
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page_option' not in st.session_state:
    st.session_state.items_per_page_option = 50  # 기본 50개
if 'search_button_clicked' not in st.session_state:
    st.session_state.search_button_clicked = False
if 'filter_column' not in st.session_state:
    st.session_state.filter_column = display_column_names[0] if display_column_names else ""
if 'filter_keyword' not in st.session_state:
    st.session_state.filter_keyword = ""
if 'selected_institution' not in st.session_state:
    st.session_state.selected_institution = ""

# ----------------- 사이드바: 검색 조건 -----------------
with st.sidebar:
    st.header("🔍 조회 조건 설정")

    today = datetime.today()
    default_start_date = today - timedelta(days=365)
    default_end_date = today - timedelta(days=1)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작 날짜", value=default_start_date)
    with col2:
        end_date = st.date_input("종료 날짜", value=default_end_date)

    contract_name = st.text_input("용역명 (필수)", placeholder="예: 통합관제센터")

    # 소관기관 selectbox (빈값 = 전체조회)
    inst_options = list(INSTITUTION_TYPES.keys())
    select_options = [""] + inst_options
    current = st.session_state.get('selected_institution', "")
    default_index = select_options.index(current) if current in select_options else 0

    ia, ib = st.columns([4, 1], gap="small")
    with ia:
        st.selectbox(
            "소관기관 (빈칸 = 전체조회)",
            options=select_options,
            index=default_index,
            key="selected_institution",
            format_func=lambda x: "선택안함" if x == "" else x,
            help="기관을 선택하면 필터가 적용됩니다. 빈칸이면 전체 조회됩니다."
        )
    with ib:
        def _clear_inst():
            st.session_state['selected_institution'] = ""
        st.button("❌", key="clear_inst", on_click=_clear_inst)

    if st.button("🚀 검색 시작!"):
        st.session_state.search_button_clicked = True
        st.session_state.current_page = 1
        st.session_state.filter_keyword = ""
        st.session_state.filter_column = display_column_names[0] if display_column_names else ""
        st.rerun()

# ----------------- 유틸 함수: 수요기관 파싱 -----------------
def parse_dminstt(entry):
    if entry is None:
        return pd.NA, pd.NA
    s = str(entry).strip()
    if s == "" or s.lower() == 'nan':
        return pd.NA, pd.NA
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    # 여러 항목이 있을 때 첫 블록만 사용
    first = s.split('][')[0]
    parts = [p.strip() for p in first.split('^')]
    name = parts[2] if len(parts) > 2 and parts[2] != '' else pd.NA
    kind = parts[3] if len(parts) > 3 and parts[3] != '' else pd.NA
    return name, kind

# ----------------- API 호출 함수 (페이지네이션 포함) -----------------
@st.cache_data(ttl=3600)
def get_contract_data(start_dt, end_dt, contract_nm, instt_type_value):
    all_data = []
    page_no = 1
    total_count = -1
    max_retries = 3

    while True:
        params = {
            'serviceKey': SERVICE_KEY,
            'pageNo': page_no,
            'numOfRows': MAX_API_ROWS,
            'inqryDiv': '1',
            'type': 'xml',
            'inqryBgnDate': start_dt.strftime("%Y%m%d"),
            'inqryEndDate': end_dt.strftime("%Y%m%d"),
            'cntrctNm': contract_nm
        }
        if instt_type_value:
            params['insttClsfcCd'] = str(instt_type_value)

        if DEBUG:
            st.sidebar.write("DEBUG API params keys:", list(params.keys()))
            st.sidebar.write("DEBUG insttClsfcCd:", params.get('insttClsfcCd'))
            st.sidebar.write("DEBUG serviceKey_present:", bool(params.get('serviceKey')))

        try:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            if DEBUG:
                st.sidebar.write("DEBUG status_code:", response.status_code)
                st.sidebar.text(response.text[:800])

            root = ET.fromstring(response.content)
            header = root.find('header')
            if header is not None:
                result_code = header.find('resultCode').text if header.find('resultCode') is not None else ''
                result_msg = header.find('resultMsg').text if header.find('resultMsg') is not None else ''
                if result_code != '00':
                    st.error(f"API 오류: {result_msg} ({result_code})")
                    return pd.DataFrame()

            body = root.find('body')
            if body is None:
                return pd.DataFrame()

            current_total_count = int(body.find('totalCount').text) if body.find('totalCount') is not None else 0
            if total_count == -1:
                total_count = current_total_count

            items = body.find('items')
            if items is not None:
                for item in items.findall('item'):
                    row = {}
                    for child in item:
                        row[child.tag] = child.text
                    all_data.append(row)

            # 종료 조건
            if total_count > 0 and len(all_data) >= total_count:
                break
            if items is not None and len(items.findall('item')) < MAX_API_ROWS:
                break

            page_no += 1
            time.sleep(0.1)

        except requests.exceptions.Timeout:
            max_retries -= 1
            if max_retries <= 0:
                st.error("API 요청 타임아웃이 반복되어 중단했습니다.")
                return pd.DataFrame()
            time.sleep(2)
            continue
        except Exception as e:
            st.error(f"데이터 조회 중 오류: {e}")
            return pd.DataFrame()

    return pd.DataFrame(all_data)

# ----------------- 검색 처리 -----------------
if st.session_state.search_button_clicked:
    inst_to_api = None
    selected_name = st.session_state.get('selected_institution', "")
    if selected_name:
        inst_to_api = INSTITUTION_TYPES.get(selected_name)

    if not contract_name or contract_name.strip() == "":
        st.warning("용역명을 입력하세요 (필수).")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame()
    elif start_date > end_date:
        st.warning("시작일은 종료일보다 클 수 없습니다.")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame()
    else:
        # 캐시 초기화(디버그 중)
        st.cache_data.clear()
        with st.spinner("데이터 조회 중..."):
            df_fetched = get_contract_data(start_date, end_date, contract_name.strip(), inst_to_api)
            # 전체 원본 숫자 정리 (다운로드용)
            df_all = df_fetched.copy()
            for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
                if col in df_all.columns:
                    df_all[col] = pd.to_numeric(df_all[col].astype(str).str.replace(',', ''), errors='coerce')

            # 수요기관명/구분 추가 (다운로드용)
            src = None
            for c in ['dminsttList', '수요기관목록']:
                if c in df_all.columns:
                    src = c
                    break
            if src:
                parsed = df_all[src].apply(parse_dminstt)
                df_all['수요기관명'], df_all['수요기관구분'] = zip(*parsed)
            else:
                df_all['수요기관명'] = pd.NA
                df_all['수요기관구분'] = pd.NA

            st.session_state.data_df = df_all.copy()
            st.session_state.filtered_data_df = df_all.copy()
            st.session_state.current_page = 1

    st.session_state.search_button_clicked = False
    st.rerun()

# ----------------- 결과 표시 -----------------
if not st.session_state.data_df.empty:
    # 페이지네이션 등
    total_rows = len(st.session_state.filtered_data_df)
    items_per_page = st.session_state.items_per_page_option
    total_pages = (total_rows + items_per_page - 1) // items_per_page if total_rows > 0 else 1

    if st.session_state.current_page > total_pages:
        st.session_state.current_page = total_pages

    start_index = (st.session_state.current_page - 1) * items_per_page
    end_index = min(start_index + items_per_page, total_rows)
    df_page = st.session_state.filtered_data_df.iloc[start_index:end_index].copy()

    # 순번 추가
    if not df_page.empty:
        if '순번' not in df_page.columns:
            df_page.insert(0, '순번', range(start_index + 1, start_index + 1 + len(df_page)))

    # 수요기관명/구분 화면용 추가 (페이지)
    src = None
    for c in ['dminsttList', '수요기관목록']:
        if c in df_page.columns:
            src = c
            break
    if src:
        parsed_page = df_page[src].apply(parse_dminstt)
        df_page['수요기관명'], df_page['수요기관구분'] = zip(*parsed_page)
    else:
        df_page['수요기관명'] = pd.NA
        df_page['수요기관구분'] = pd.NA

    # 화면에 표시할 컬럼 정리
    cols_to_display = ['순번'] + [c for c in display_columns_map.keys() if c in df_page.columns]
    df_display = df_page[cols_to_display].copy()
    df_display.rename(columns={**display_columns_map, '순번': '순번'}, inplace=True)

    # 인덱스 숨김
    df_display.index = [''] * len(df_display)

    # 숫자 타입 보장 (페이지)
    for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(df_display[col].astype(str).str.replace(',', ''), errors='coerce')

    # AgGrid 표시 (권장)
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
        items_per_page = st.session_state.get('items_per_page_option', 50)
        ROW_PX = 30
        table_height = ROW_PX * int(items_per_page) + 60

        gb = GridOptionsBuilder.from_dataframe(df_display)
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=int(items_per_page))

        format_js = JsCode("""
        function(params) {
            if (params.value === null || params.value === undefined || params.value === '') {
                return '';
            }
            return Number(params.value).toLocaleString('ko-KR');
        }
        """)

        for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
            if col in df_display.columns:
                gb.configure_column(
                    field=col,
                    valueFormatter=format_js,
                    cellStyle={'textAlign': 'right'}
                )

        if '순번' in df_display.columns:
            gb.configure_column(field='순번', cellStyle={'textAlign': 'right'})

        grid_options = gb.build()
        AgGrid(df_display, gridOptions=grid_options, fit_columns_on_grid_load=True, height=int(table_height), allow_unsafe_jscode=True)
    except Exception as e:
        # Styler 폴백
        format_map = {col: "{:,.0f}" for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS if col in df_display.columns}
        try:
            styled = df_display.style.format(format_map).set_properties(**{'text-align': 'right'}, subset=list(format_map.keys()))
            st.dataframe(styled, use_container_width=True, height=600)
        except Exception:
            df_viz = df_display.copy()
            for col in format_map:
                df_viz[col] = df_viz[col].apply(lambda x: format(x, ",.0f") if pd.notnull(x) else "")
            st.dataframe(df_viz, use_container_width=True, height=600)
else:
    st.info("용역명과 조회 기간을 설정한 뒤 '검색 시작'을 눌러주세요.")

# ----------------- 다운로드 (전체 데이터, 숫자 그대로 저장) -----------------
if not st.session_state.data_df.empty:
    # df_for_download는 이미 st.session_state.data_df
    df_for_download = st.session_state.data_df.copy()
    # 금액 숫자 보정
    for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
        if col in df_for_download.columns:
            df_for_download[col] = pd.to_numeric(df_for_download[col].astype(str).str.replace(',', ''), errors='coerce')

    # 다운로드 버튼
    csv_bytes = df_for_download.to_csv(index=False, encoding='utf-8-sig')
    st.download_button("⬇️ CSV 다운 (숫자)", data=csv_bytes, file_name=f"계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")
    buf = io.BytesIO()
    df_for_download.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    st.download_button("⬇️ XLSX 다운 (숫자)", data=buf, file_name=f"계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
