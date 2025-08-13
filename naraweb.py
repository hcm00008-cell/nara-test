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

# --- 환경 로드 (.env 사용 시) ---
load_dotenv()  # 로컬에서 .env 파일을 사용하는 경우에 유용

# 디버그 모드 설정: Streamlit Cloud/Actions에 NARA_DEBUG=true/false로 설정 가능
DEBUG = os.getenv("NARA_DEBUG", "false").lower() in ("1", "true", "yes")

# --- 서비스 키 (환경변수에서 읽기) ---
SERVICE_KEY = os.getenv("NARA_SERVICE_KEY")
if not SERVICE_KEY:
    import streamlit as st
    st.warning("환경변수 NARA_SERVICE_KEY가 설정되어 있지 않습니다. GitHub Secrets에 추가하세요.")
API_URL = 'http://apis.data.go.kr/1230000/ao/CntrctInfoService/getCntrctInfoListServcPPSSrch'
MAX_API_ROWS = 999  # API가 한 번에 반환하는 최대 개수

# --- 화면 표시용 컬럼 매핑 (반드시 UI 초기화보다 먼저 정의) ---
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
reverse_display_columns_map = {v: k for k, v in display_columns_map.items()}

# --- 다운로드용 컬럼 한글 매핑 (필요하면 확장) ---
DOWNLOAD_COLUMN_MAP = {
    'resultCode': '결과코드',
    'resultMsg': '결과메세지',
    'numOfRows': '한 페이지 결과 수',
    'pageNo': '페이지 번호',
    'totalCount': '전체 결과 수',
    'untyCntrctNo': '통합계약번호',
    'bsnsDivNm': '업무구분명',
    'dcsnCntrctNo': '확정계약번호',
    'cntrctRefNo': '계약참조번호',
    'cntrctNm': '계약명',
    'cmmnCntrctYn': '공동계약여부',
    'lngtrmCtnuDivNm': '장기계속구분명',
    'cntrctCnclsDate': '계약체결일자',
    'cntrctPrd': '계약기간',
    'baseLawNm': '근거법률명',
    'totCntrctAmt': '총계약금액',
    'thtmCntrctAmt': '금차계약금액',
    'grntymnyRate': '보증금률',
    'cntrctInfoUrl': '계약정보URL',
    'payDivNm': '지급구분명',
    'reqNo': '요청번호',
    'ntceNo': '공고번호',
    'cntrctInsttCd': '계약기관코드',
    'cntrctInsttNm': '계약기관명',
    'cntrctInsttJrsdctnDivNm': '계약기관소관구분명',
    'cntrctInsttChrgDeptNm': '계약기관담당부서명',
    'cntrctInsttOfclNm': '계약기관담당자명',
    'cntrctInsttOfclTelNo': '계약기관담당자전화번호',
    'cntrctInsttOfclFaxNo': '계약기관담당자팩스번호',
    'dminsttList': '수요기관목록',
    'corpList': '업체목록',
    'cntrctDtlInfoUrl': '계약상세정보URL',
    'crdtrNm': '채권자명',
    'baseDtls': '근거내역',
    'cntrctCnclsMthdNm': '계약체결방법명',
    'rgstDt': '등록일시',
    'chgDt': '변경일시',
    'dfrcmpnstRt': '지체상금율',
    'wbgnDate': '착수일자',
    'thtmScmpltDate': '금차완수일자',
    'ttalScmpltDate': '총완수일자',
    'pubPrcrmntLrgclsfcNm ': '공공조달대분류명',
    'pubPrcrmntMidclsfcNm': '공공조달중분류명',
    'pubPrcrmntClsfcNo': '공공조달분류번호',
    'pubPrcrmntClsfcNm': '공공조달분류명',
    'cntrctDate': '계약일자',
    'infoBizYn': '정보화사업여부'
}
DOWNLOAD_AMOUNT_ORIGINAL_COLS = ['totCntrctAmt', 'thtmCntrctAmt']

# --- 소관기관 코드 매핑 (첨부된 매핑 사용) ---
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

# --- Streamlit 페이지 설정 ---
st.set_page_config(page_title="나라장터 계약 내역 조회", layout="wide")
st.title("🏛️ 나라장터 용역 계약 내역 조회")

# --- Session state 초기화 (변수 정의 이후) ---
if 'data_df' not in st.session_state:
    st.session_state.data_df = pd.DataFrame()
if 'filtered_data_df' not in st.session_state:
    st.session_state.filtered_data_df = pd.DataFrame()
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page_option' not in st.session_state:
    st.session_state.items_per_page_option = 50
if 'search_button_clicked' not in st.session_state:
    st.session_state.search_button_clicked = False
if 'filter_column' not in st.session_state:
    st.session_state.filter_column = display_column_names[0] if display_column_names else ""
if 'filter_keyword' not in st.session_state:
    st.session_state.filter_keyword = ""
if 'selected_institution' not in st.session_state:
    st.session_state.selected_institution = ""

# --- 사이드바: 검색 조건 ---
with st.sidebar:
    # 좌측 상단 고정 배지: 글자 굵게, 20pt
    st.markdown(
        """
        <div style="
            position: fixed;
            top: 8px;
            left: 8px;
            background: rgba(255,220,216,0.90);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 18pt;
            font-weight: 700;
            color: #222;
            z-index: 9999;
            box-shadow: 0 2px 6px rgba(0,0,0,0.12);
        ">
            "by. 솔루션사업부문
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.header("🔍 조회 조건 설정")
    

    today = datetime.today()
    default_start_date = today - timedelta(days=365)
    default_end_date = today - timedelta(days=1)  # 어제

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작 날짜", value=default_start_date)
    with col2:
        end_date = st.date_input("종료 날짜", value=default_end_date)

    contract_name = st.text_input("용역명 (필수)", placeholder="예: 통합관제센터")

    # 소관기관: 빈값(전체) 허용, 선택 후 ❌로 초기화
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
    # 콜백 함수 정의 (사이드바 블록 바깥이나 안쪽 어디든 가능)
    def _clear_selected_institution():
        # 안전하게 세션 상태 초기화
        st.session_state['selected_institution'] = ""

    # 버튼에 on_click으로 콜백 연결 (이 방식이 안전함)
    with ib:
        st.button("❌", key="clear_inst", on_click=_clear_selected_institution)

    # 검색 버튼
    if st.button("🚀 검색 시작!"):
        st.session_state.search_button_clicked = True
        st.session_state.current_page = 1
        st.session_state.filter_keyword = ""
        st.session_state.filter_column = display_column_names[0] if display_column_names else ""
        st.rerun()

# --- API 호출 함수: 페이지네이션 포함 ---
@st.cache_data(ttl=3600)
def get_contract_data(start_dt, end_dt, contract_nm, instt_type_value):
    all_data = []
    page_no = 1
    total_count = -1

    max_retries = 3
    retry_count = 0

    while True:
        st.info(f"데이터를 불러오는 중입니다... (페이지: {page_no})")
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
        # 디버그: params 확인 (주의: serviceKey 값 자체는 출력하지 않음)
       
        if DEBUG:
            st.sidebar.write("DEBUG params keys:", list(params.keys()))
            st.sidebar.write("DEBUG insttClsfcCd:", params.get('insttClsfcCd'))
            st.sidebar.write("DEBUG serviceKey_present:", bool(params.get('serviceKey')))
        
        response = requests.get(API_URL, params=params, timeout=30)
        
        if DEBUG:
            st.sidebar.write("DEBUG status_code:", response.status_code)
            st.sidebar.text(response.text[:1500])

        # API가 요구하는 소관기관 파라미터명으로 전송
        if instt_type_value:
            params['insttClsfcCd'] = str(instt_type_value)

        # (디버그용) 요청 파라미터 확인 - 필요시 주석 해제
        # st.sidebar.write("DEBUG API params:", params)

        try:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
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

            # 종료 조건: 전체 개수에 도달했거나 현재 페이지 아이템 수가 MAX보다 적으면 끝
            if total_count > 0 and len(all_data) >= total_count:
                break
            if items is not None and len(items.findall('item')) < MAX_API_ROWS:
                break

            page_no += 1
            retry_count = 0

        except requests.exceptions.Timeout:
            retry_count += 1
            if retry_count <= max_retries:
                st.warning(f"타임아웃 발생! ({retry_count}/{max_retries} 재시도 중...)")
                time.sleep(2)
                continue
            else:
                st.error("타임아웃 - 나중에 다시 시도해주세요.")
                return pd.DataFrame()
        except requests.exceptions.RequestException as e:
            st.error(f"네트워크/API 오류: {e}")
            return pd.DataFrame()
        except ET.ParseError:
            st.error("XML 파싱 오류 - 응답 확인 필요")
            return pd.DataFrame()
        except Exception as e:
            st.error(f"알 수 없는 오류: {e}")
            return pd.DataFrame()

    st.success(f"총 {len(all_data)}건을 불러왔습니다!")
    return pd.DataFrame(all_data)

# --- 검색 실행 처리 ---
if st.session_state.search_button_clicked:
    inst_to_api = None
    selected_name = st.session_state.get('selected_institution', "")
    if selected_name:
        inst_to_api = INSTITUTION_TYPES.get(selected_name)

    # 유효성 검사
    if not contract_name or contract_name.strip() == "":
        st.warning("용역명을 입력하세요 (필수).")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame()
    elif start_date > end_date:
        st.warning("시작일은 종료일보다 클 수 없습니다.")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame()
    else:
        st.cache_data.clear()
        with st.spinner("데이터 조회 중..."):
            df_fetched = get_contract_data(start_date, end_date, contract_name.strip(), inst_to_api)
            st.session_state.data_df = df_fetched.copy()
            st.session_state.filtered_data_df = df_fetched.copy()
            st.session_state.current_page = 1

    st.session_state.search_button_clicked = False
    st.rerun()

# --- 메인 화면: 필터, 페이지당 표시, 다운로드, 테이블, 페이지네이션 (display only) ---
if not st.session_state.data_df.empty:
    # 상단 컨트롤 (필터 + 페이지당 표시)
    left_col, right_col = st.columns([7, 3], gap="small")
    with left_col:
        st.subheader(f"📊 조회 결과 (총 {len(st.session_state.filtered_data_df)}건)")
        f0, f1, f2, f3 = st.columns([1.5, 3, 1.2, 1], gap="small")
        with f0:
            # 안전한 selectbox 초기화
            initial_index = 0
            if st.session_state.get('filter_column') in display_column_names:
                initial_index = display_column_names.index(st.session_state['filter_column'])
            st.session_state.filter_column = st.selectbox("", options=display_column_names, index=initial_index, key="filter_column_selector", label_visibility="collapsed")

        with f1:
            st.session_state.filter_keyword = st.text_input("", value=st.session_state.filter_keyword, placeholder=f"'{st.session_state.filter_column}'에서 검색할 키워드를 입력하세요", key="filter_keyword_input", label_visibility="collapsed")
        with f2:
            if st.button("필터 적용", key="apply_filter_button"):
                temp_df = st.session_state.data_df.copy()
                api_col = reverse_display_columns_map.get(st.session_state.filter_column)
                if st.session_state.filter_keyword and api_col in temp_df.columns:
                    kw = st.session_state.filter_keyword.lower()
                    temp_df = temp_df[temp_df[api_col].astype(str).str.lower().str.contains(kw, na=False)]
                st.session_state.filtered_data_df = temp_df
                st.session_state.current_page = 1
                st.rerun()
        with f3:
            sel = st.selectbox("", options=[10,30,50,100], index=[10,30,50,100].index(st.session_state.items_per_page_option), key="items_per_page_selector", label_visibility="collapsed")
            if sel != st.session_state.items_per_page_option:
                st.session_state.items_per_page_option = sel
                st.session_state.current_page = 1
                st.rerun()

    with right_col:
        st.markdown("<br>", unsafe_allow_html=True)
        dlc1, dlc2 = st.columns([1,1], gap="small")
        with dlc1:
            df_csv = st.session_state.data_df.copy()
            df_csv.rename(columns=DOWNLOAD_COLUMN_MAP, inplace=True)
            for col_original in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
                col_k = DOWNLOAD_COLUMN_MAP.get(col_original)
                if col_k and col_k in df_csv.columns:
                    df_csv[col_k] = pd.to_numeric(df_csv[col_k].astype(str).str.replace(',', ''), errors='coerce')
            csv_bytes = df_csv.to_csv(index=False, encoding='utf-8-sig')
            st.download_button("⬇️ CSV 다운", data=csv_bytes, file_name=f"계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", key="dl_csv", use_container_width=True)
        with dlc2:
            df_xlsx = st.session_state.data_df.copy()
            df_xlsx.rename(columns=DOWNLOAD_COLUMN_MAP, inplace=True)
            for col_original in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
                col_k = DOWNLOAD_COLUMN_MAP.get(col_original)
                if col_k and col_k in df_xlsx.columns:
                    df_xlsx[col_k] = pd.to_numeric(df_xlsx[col_k].astype(str).str.replace(',', ''), errors='coerce')
            buf = io.BytesIO()
            df_xlsx.to_excel(buf, index=False, engine='openpyxl')
            buf.seek(0)
            st.download_button("⬇️ XLSX 다운", data=buf, file_name=f"계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_xlsx", use_container_width=True)

    # 테이블 표시 준비
    total_rows = len(st.session_state.filtered_data_df)
    items_per_page = st.session_state.items_per_page_option
    total_pages = (total_rows + items_per_page - 1) // items_per_page if total_rows > 0 else 1

    if st.session_state.current_page > total_pages:
        st.session_state.current_page = total_pages
        st.rerun()

    start_index = (st.session_state.current_page - 1) * items_per_page
    end_index = min(start_index + items_per_page, total_rows)
    df_page = st.session_state.filtered_data_df.iloc[start_index:end_index].copy()
    # # 순번 추가하는 부분(기존 유지)
    # 기존 순번 추가, 컬럼 순서 지정 등은 동일
    if not df_page.empty:
        if '순번' not in df_page.columns:
            df_page.insert(0, '순번', range(start_index + 1, start_index + 1 + len(df_page)))
    
    cols_to_display = ['순번'] + [c for c in display_columns_map.keys() if c in df_page.columns and c != '순번']
    
    df_display = df_page[cols_to_display].copy()
    df_display.rename(columns={**display_columns_map, '순번': '순번'}, inplace=True)
    
    # 기본 인덱스 제거
    df_display = df_display.reset_index(drop=True).copy()
    
    for col in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(
                df_display[col].astype(str).str.replace(',', '').str.strip(),
                errors='coerce'   # 변환 불가하면 NaN
            )
    st.sidebar.write({c: str(df_display[c].dtype) for c in DOWNLOAD_AMOUNT_ORIGINAL_COLS if c in df_display.columns})
    # st.sidebar.write(df_display[DOWNLOAD_AMOUNT_ORIGINAL_COLS].head().to_dict())
    
    # AgGrid 옵션 설정
    items_per_page = st.session_state.get('items_per_page_option', 50)
    ROW_PX = 30
    table_height = ROW_PX * int(items_per_page) + 60
    
    gb = GridOptionsBuilder.from_dataframe(df_display)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=int(items_per_page))
    
    # JS 포맷터(숫자 유지, 화면 포맷)
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
                col,
                valueFormatter=format_js,
                cellStyle={'textAlign': 'right'}
            )
    
    # 순번 우측정렬 원하면
    if '순번' in df_display.columns:
        gb.configure_column('순번', cellStyle={'textAlign': 'right'})
    
    grid_options = gb.build()
    AgGrid(df_display, gridOptions=grid_options, fit_columns_on_grid_load=True, height=int(table_height))


    # 페이지네이션 UI (가운데 정렬)
    st.markdown("<br>", unsafe_allow_html=True)
    current_block = (st.session_state.current_page - 1) // 10
    start_page = current_block * 10 + 1
    end_page = min(start_page + 9, total_pages)

    page_buttons = []
    if start_page > 1:
        page_buttons.append(("«", start_page - 1))
    if st.session_state.current_page > 1:
        page_buttons.append(("⬅", st.session_state.current_page - 1))
    for i in range(start_page, end_page + 1):
        page_buttons.append((str(i), i))
    if st.session_state.current_page < total_pages:
        page_buttons.append(("➡", st.session_state.current_page + 1))
    if end_page < total_pages:
        page_buttons.append(("»", end_page + 1))

    btn_w = 0.06
    total_w = len(page_buttons) * btn_w
    pad = (1.0 - total_w) / 2 if total_w < 1.0 else 0.0
    cols = st.columns([pad] + [btn_w] * len(page_buttons) + [pad])
    for idx, (txt, pg) in enumerate(page_buttons):
        with cols[idx + 1]:
            if txt.isdigit() and st.session_state.current_page == pg:
                if st.button(f"**{txt}**", key=f"pg_{pg}", use_container_width=True):
                    st.session_state.current_page = pg
                    st.rerun()
            else:
                if st.button(txt, key=f"pg_{txt}_{pg}", use_container_width=True):
                    st.session_state.current_page = pg
                    st.rerun()

else:
    st.info("용역명과 조회 기간을 설정한 뒤 '검색 시작'을 눌러주세요.")




































