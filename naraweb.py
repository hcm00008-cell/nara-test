import streamlit as st
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timedelta
import io # io 모듈 추가 (바이너리 데이터 처리용)
import os
from dotenv import load_dotenv  # 로컬 테스트용(선택)
load_dotenv()  # .env가 있으면 로드

SERVICE_KEY = os.getenv("NARA_SERVICE_KEY")
if not SERVICE_KEY:
    # 개발 중엔 경고만 띄우고, 배포 시에는 반드시 세팅해야 함
    st.warning("환경변수 NARA_SERVICE_KEY가 설정되어 있지 않습니다. GitHub Secrets에 추가하세요.")
API_URL = 'http://apis.data.go.kr/1230000/ao/CntrctInfoService/getCntrctInfoListServcPPSSrch'
MAX_API_ROWS = 999 # API가 한 번에 가져올 수 있는 최대 데이터 수

st.set_page_config(
    page_title="나라장터 계약 내역 조회",
    layout="wide" # 넓은 화면으로 시원하게
)

st.title("🏛️ 나라장터 용역 계약 내역 조회")

# --- Streamlit Session State 초기화 ---
if 'data_df' not in st.session_state:
    st.session_state.data_df = pd.DataFrame() # API에서 불러온 원본 데이터 (필터링 전)
if 'filtered_data_df' not in st.session_state:
    st.session_state.filtered_data_df = pd.DataFrame() # 키워드 필터링된 데이터
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'items_per_page_option' not in st.session_state:
    st.session_state.items_per_page_option = 10 # 기본 10개 표시
if 'search_button_clicked' not in st.session_state:
    st.session_state.search_button_clicked = False # 검색 버튼 클릭 여부
if 'filter_column' not in st.session_state: # 키워드 검색을 위한 컬럼 선택
    st.session_state.filter_column = ""
if 'filter_keyword' not in st.session_state: # 키워드 검색어
    st.session_state.filter_keyword = ""


# 소관기관구분 코드와 매핑 딕셔너리
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

# --- 🔥 다운로드용 컬럼 전체 한글 매핑 정의 🔥 ---
DOWNLOAD_COLUMN_MAP = {
    'resultCode': '결과코드', # 이 항목들은 item 안에 없을 수 있으니 참고!
    'resultMsg': '결과메세지', # item 안에 없음
    'numOfRows': '한 페이지 결과 수', # item 안에 없음
    'pageNo': '페이지 번호', # item 안에 없음
    'totalCount': '전체 결과 수', # item 안에 없음
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
    'pubPrcrmntLrgclsfcNm ': '공공조달대분류명', # 공백 주의
    'pubPrcrmntMidclsfcNm': '공공조달중분류명',
    'pubPrcrmntClsfcNo': '공공조달분류번호',
    'pubPrcrmntClsfcNm': '공공조달분류명',
    'cntrctDate': '계약일자',
    'infoBizYn': '정보화사업여부'
}

# 금액 항목 (다운로드 시 콤마 제거할 원본 컬럼명)
DOWNLOAD_AMOUNT_ORIGINAL_COLS = ['totCntrctAmt', 'thtmCntrctAmt']


# --- 조회 항목 (페이지 상단 위치) ---
with st.sidebar: # 사이드바에 필터 넣어서 깔끔하게!
    st.header("🔍 조회 조건 설정")
    
    # 기본 시작/종료 날짜 설정 (최근 1년 정도?)
    today = datetime.today()
    default_start_date = today - timedelta(days=365) # 예시로 1년 전부터 시작
    default_end_date = today - timedelta(days=1) # 🔥 종료날짜는 하루 전으로 세팅 🔥

    # 날짜 입력 위젯
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("🗓️ 시작 날짜", value=default_start_date)
    with col2:
        end_date = st.date_input("🗓️ 종료 날짜", value=default_end_date)

    # 용역명 입력 위젯
    contract_name = st.text_input("📝 용역명 (ex: 통합관제센터)", placeholder="검색할 용역명을 입력하세요.")

    # 🔥 소관기관구분 단일 선택으로 변경 🔥
    selected_institution = st.selectbox(
        "🏛️ 소관기관구분 (1개 선택)", # 레이블 변경
        options=list(INSTITUTION_TYPES.keys()), # 텍스트만 보이도록 keys() 사용
        index=0 # 기본값 첫 번째 항목으로 설정
    )
    
    # 소관기관구분 직접 입력 (선택지에 없는 경우)
    custom_institution_type = st.text_input(
        "직접 입력할 소관기관명 (위 목록에 없는 경우)",
        placeholder="예: 서울특별시, 경기도교육청 등" # 사용자에게 텍스트 예시 제공
    )

    # 검색 버튼
    if st.button("🚀 검색 시작!"):
        st.session_state.search_button_clicked = True
        st.session_state.current_page = 1 # 새 검색 시작 시 페이지 리셋
        st.session_state.filter_keyword = "" # 검색 시작 시 키워드 필터 초기화
        # st.session_state.filter_column = "" # 검색 시작 시 키워드 필터 컬럼 초기화는 첫 번째 컬럼으로 설정됨


# --- 데이터 가져오기 함수 (API 호출) ---
@st.cache_data(ttl=3600) # 한 시간 동안 데이터 캐싱해서 API 호출 최소화
def get_contract_data(start_dt, end_dt, contract_nm, instt_type_value): # 기관 타입 코드가 아닌, API에 보낼 최종 값을 받음
    all_data = []
    page_no = 1
    total_count = -1 

    max_retries = 3
    retry_count = 0

    while True:
        st.info(f"데이터를 불러오는 중입니다... (API 페이지: {page_no} / 총 데이터: {len(all_data)} 건)")
        
        params = {
            'serviceKey': SERVICE_KEY,
            'pageNo': page_no,
            'numOfRows': MAX_API_ROWS,
            'inqryDiv': '1', # 서비스 구분 (1: 용역)
            'type': 'xml',
            'inqryBgnDate': start_dt.strftime("%Y%m%d"),
            'inqryEndDate': end_dt.strftime("%Y%m%d"),
            'cntrctNm': contract_nm # 검색어
        }
        
        # 소관기관구분 파라미터 추가 (instt_type_value가 있을 경우)
        if instt_type_value:
            params['cntrctInsttJrsdctnDivNm'] = instt_type_value # 이 값은 코드('01')이거나 직접 입력 텍스트
        
        try:
            response = requests.get(API_URL, params=params, timeout=30) 
            response.raise_for_status()

            root = ET.fromstring(response.content)
            
            header = root.find('header')
            result_code = header.find('resultCode').text
            result_msg = header.find('resultMsg').text
            
            if result_code != '00':
                st.error(f"API 호출 중 오류 발생: {result_msg} (코드: {result_code})")
                return pd.DataFrame()

            body = root.find('body')
            items = body.find('items')
            
            current_total_count = int(body.find('totalCount').text) if body.find('totalCount') is not None else 0
            if total_count == -1: 
                total_count = current_total_count

            if items is not None:
                for item in items.findall('item'):
                    row = {}
                    for child in item:
                        row[child.tag] = child.text
                    all_data.append(row)
            
            if len(all_data) >= total_count:
                break
            
            if items is not None and len(items.findall('item')) < MAX_API_ROWS:
                break

            page_no += 1
            retry_count = 0

        except requests.exceptions.Timeout:
            retry_count += 1
            if retry_count <= max_retries:
                st.warning(f"타임아웃 발생! ({retry_count}/{max_retries} 재시도 중...) 잠시 기다려 주세요.")
                import time
                time.sleep(2) 
                continue
            else:
                st.error(f"연결 타임아웃 오류: {max_retries}번 재시도 후에도 응답이 없습니다.")
                return pd.DataFrame()
        except requests.exceptions.RequestException as e:
            st.error(f"네트워크 오류 또는 API 연결 실패: {e}")
            return pd.DataFrame()
        except ET.ParseError:
            st.error("API 응답이 유효한 XML 형식이 아닙니다. 응답 내용을 확인해주세요.")
            st.code(response.text)
            return pd.DataFrame()
        except Exception as e:
            st.error(f"데이터 처리 중 알 수 없는 오류 발생: {e}")
            return pd.DataFrame()
            
    st.success(f"총 {len(all_data)}건의 데이터를 성공적으로 불러왔습니다! 👏")
    return pd.DataFrame(all_data)

# --- 화면에 표시할 컬럼 정의 (원본 API 컬럼명: 한글 표시명) ---
# 이건 화면 UI용이므로 이전과 동일하게 유지
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
# 한글 표시명을 기준으로 드롭다운 옵션 제공 (키워드 검색용)
display_column_names = list(display_columns_map.values())
# 역매핑 (한글 표시명: 원본 API 컬럼명)
reverse_display_columns_map = {v: k for k, v in display_columns_map.items()}

# --- 데이터 로딩 및 검색 버튼 로직 ---
if st.session_state.search_button_clicked:
    instt_type_to_api = None # API로 전달할 최종 소관기관 값

    # 🔥 단일 선택이므로 selected_institutions -> selected_institution 으로 변경 🔥
    if selected_institution: # 사용자가 선택한 기관이 있다면
        # 사용자가 선택한 기관의 '이름'으로 '코드'를 찾음
        instt_type_to_api = INSTITUTION_TYPES.get(selected_institution)
        if not instt_type_to_api: # 선택된 기관의 코드를 찾을 수 없다면
            st.warning(f"선택하신 '{selected_institution}'에 대한 유효한 API 코드를 찾을 수 없습니다. API에 반영되지 않을 수 있습니다.")
    
    # 2. 직접 입력값이 있다면 직접 입력값을 사용 (선택 항목보다 우선하지 않음)
    if custom_institution_type:
        instt_type_to_api = custom_institution_type
        st.warning(f"직접 입력하신 '{custom_institution_type}'는 유효한 API 코드가 아닐 수 있습니다. 검색 결과가 예상과 다를 수 있습니다.")
    
    # 검색 조건 유효성 검사
    if not contract_name:
        st.warning("🚨 용역명을 입력해주세요!")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame() 
    elif start_date > end_date:
        st.warning("🚨 시작 날짜는 종료 날짜보다 빠를 수 없습니다!")
        st.session_state.data_df = pd.DataFrame()
        st.session_state.filtered_data_df = pd.DataFrame() 
    else:
        st.cache_data.clear() 
        with st.spinner("⏳ 데이터 조회 중... 잠시만 기다려주세요."):
            df_fetched = get_contract_data(start_date, end_date, contract_name, instt_type_to_api)
            st.session_state.data_df = df_fetched # 원본 데이터 저장
            st.session_state.filtered_data_df = df_fetched.copy() # 초기에는 필터링된 데이터 = 원본 데이터
            # filter_column 초기값 설정 (가장 첫 번째 display_column_name)
            if display_column_names:
                st.session_state.filter_column = display_column_names[0]
            else:
                st.session_state.filter_column = ""
            st.session_state.filter_keyword = "" # 필터 키워드도 초기화
    st.session_state.search_button_clicked = False # 검색 프로세스 완료 (False로 리셋)

# --- 메인 컨텐츠 영역 시작 ---
if not st.session_state.data_df.empty:
    # --- 상단 컨트롤바 (필터, 페이지당 표시, 다운로드 버튼) 🔥 같은 라인으로 배치 🔥---
    # 큰 두 개의 컬럼으로 나누고, 그 안에서 또 서브 컬럼으로 나누는 방식
    # 이렇게 해야 필터 섹션과 다운로드 버튼이 한 줄에 배치될 수 있음.
    # 비율을 조정해서 오른쪽 (다운로드) 영역을 작게 유지
    filter_download_line_col1, filter_download_line_col2 = st.columns([7, 3], gap="small") # 필터 섹션이 더 넓게

    with filter_download_line_col1: # 필터와 페이지당 표시 갯수 섹션
        st.subheader(f"📊 조회 결과 (총 {len(st.session_state.filtered_data_df)}건)", anchor=False) # 타이틀 제거, 서브헤더로
        
        # 필터 컴포넌트들을 한 줄에 배치하기 위한 컬럼
        filter_cols = st.columns([1.5, 3, 1.5, 1], gap="small") # 컬럼 선택, 검색어, 필터버튼, 표시갯수

        with filter_cols[0]:
            st.session_state.filter_column = st.selectbox(
                "", # 레이블 숨기기
                options=display_column_names,
                index=display_column_names.index(st.session_state.filter_column) if st.session_state.filter_column in display_column_names else 0,
                key="filter_column_selector",
                label_visibility="collapsed"
            )
        with filter_cols[1]:
            st.session_state.filter_keyword = st.text_input(
                "", # 레이블 숨기기
                value=st.session_state.filter_keyword,
                placeholder=f"'{st.session_state.filter_column}'에서 검색할 키워드를 입력하세요",
                key="filter_keyword_input",
                label_visibility="collapsed"
            )
        
        with filter_cols[2]:
            st.markdown("<br>", unsafe_allow_html=True) # 줄 맞춤용
            if st.button("필터 적용", key="apply_filter_button"):
                # 필터 적용 시 현재 필터된 상태를 다시 필터링 (새로운 data_df에서 시작)
                temp_df = st.session_state.data_df.copy() # 원본 데이터 복사
                column_to_filter_api_name = reverse_display_columns_map.get(st.session_state.filter_column)
                if st.session_state.filter_keyword and column_to_filter_api_name in temp_df.columns:
                    keyword = st.session_state.filter_keyword.lower()
                    temp_df = temp_df[temp_df[column_to_filter_api_name].astype(str).str.lower().str.contains(keyword, na=False)]
                
                st.session_state.filtered_data_df = temp_df # 필터링 결과 저장
                st.session_state.current_page = 1 # 필터 적용 시 첫 페이지로 이동
                st.rerun() # 변경사항 적용을 위해 리렌더링 (리런 안하면 apply_filter_button 상태로 인해 버그)

        with filter_cols[3]: # 페이지당 표시 갯수
            items_per_page = st.selectbox(
                "", # 레이블 숨기기
                options=[10, 30, 50, 100],
                index=[10, 30, 50, 100].index(st.session_state.items_per_page_option),
                key="items_per_page_selector",
                label_visibility="collapsed"
            )
            if items_per_page != st.session_state.items_per_page_option:
                st.session_state.items_per_page_option = items_per_page
                st.session_state.current_page = 1 # 페이지당 표시 개수 변경 시 첫 페이지로 이동
                st.rerun() 

    with filter_download_line_col2: # 다운로드 버튼 섹션 🔥 우측 상단으로 이동 🔥
        st.markdown("<br>", unsafe_allow_html=True) # 줄 맞춤용
        # 다운로드 버튼 2개를 나란히 배치하기 위한 컬럼, 비율을 1:1로 해서 크기를 같게
        download_cols = st.columns([1,1], gap="small") 
        
        with download_cols[0]:
            # 🔥 CSV 다운로드용 DataFrame 준비 및 컬럼명 변경, 금액 포맷팅 없음 🔥
            df_for_download_csv = st.session_state.data_df.copy()
            # DOWNLOAD_COLUMN_MAP을 사용하여 컬럼명 변경 (기존에 없는 컬럼명은 무시)
            df_for_download_csv.rename(columns=DOWNLOAD_COLUMN_MAP, inplace=True)
            
            # 금액 컬럼들은 쉼표 없이 숫자로 (혹시 모를 문자열 -> 숫자 변환)
            for col_original in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
                col_korean = DOWNLOAD_COLUMN_MAP.get(col_original) # 한글명 가져오기
                if col_korean and col_korean in df_for_download_csv.columns:
                    # pd.to_numeric을 사용해서 숫자 아닌 값은 NaN으로 처리
                    df_for_download_csv[col_korean] = pd.to_numeric(
                        df_for_download_csv[col_korean].astype(str).str.replace(',', ''), 
                        errors='coerce' # 숫자로 변환 불가한 경우 NaN으로 처리
                    )
            
            csv_data = df_for_download_csv.to_csv(index=False, encoding='utf-8-sig') 
            st.download_button(
                label="⬇️ CSV 다운", # 레이블 줄이기
                data=csv_data,
                file_name=f"나라장터_계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", # 파일명에 현재 시간 추가
                mime="text/csv",
                key="download_csv_button",
                use_container_width=True # 버튼 크기 조절
            )
        with download_cols[1]:
            # 🔥 XLSX 다운로드용 DataFrame 준비 및 컬럼명 변경, 금액 포맷팅 없음 🔥
            df_for_download_xlsx = st.session_state.data_df.copy()
            # DOWNLOAD_COLUMN_MAP을 사용하여 컬럼명 변경
            df_for_download_xlsx.rename(columns=DOWNLOAD_COLUMN_MAP, inplace=True)
            
            # 금액 컬럼들은 쉼표 없이 숫자로
            for col_original in DOWNLOAD_AMOUNT_ORIGINAL_COLS:
                col_korean = DOWNLOAD_COLUMN_MAP.get(col_original)
                if col_korean and col_korean in df_for_download_xlsx.columns:
                    df_for_download_xlsx[col_korean] = pd.to_numeric(
                        df_for_download_xlsx[col_korean].astype(str).str.replace(',', ''), 
                        errors='coerce'
                    )

            excel_buffer = io.BytesIO() 
            df_for_download_xlsx.to_excel(excel_buffer, index=False, engine='openpyxl')
            excel_buffer.seek(0)
            st.download_button(
                label="⬇️ XLSX 다운", # 레이블 줄이기
                data=excel_buffer,
                file_name=f"나라장터_계약내역_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", # 파일명에 현재 시간 추가
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_xlsx_button",
                use_container_width=True # 버튼 크기 조절
            )
            
    # --- 실제 테이블 표시 ---
    total_rows = len(st.session_state.filtered_data_df) # 필터링된 데이터 기준으로 총 행 수 계산
    items_per_page = st.session_state.items_per_page_option
    total_pages = (total_rows + items_per_page - 1) // items_per_page
    
    # 현재 페이지가 총 페이지를 초과하면 조정
    if st.session_state.current_page > total_pages and total_pages > 0:
        st.session_state.current_page = total_pages
        st.rerun()
    elif st.session_state.current_page == 0 and total_pages > 0: # 0페이지가 되는 경우 1페이지로
        st.session_state.current_page = 1
        st.rerun()
    elif total_pages == 0: # 데이터가 없으면 현재 페이지 1로 강제 설정 (표시될게 없어도)
        st.session_state.current_page = 1

    # 선택된 페이지에 해당하는 데이터 슬라이싱 (필터링된 데이터에서 슬라이싱)
    start_index = (st.session_state.current_page - 1) * items_per_page
    end_index = min(start_index + items_per_page, total_rows)
    df_display = st.session_state.filtered_data_df.iloc[start_index:end_index].copy() # .copy()를 사용하여 원본 데이터프레임의 슬라이스가 아닌 독립적인 복사본으로 작업

    # --- 순번 컬럼 추가 및 화면에 표시할 컬럼 선택, 이름 변경, 금액 포맷팅 적용 ---
    if not df_display.empty:
        # 순번 컬럼 추가
        # 시작 인덱스를 기준으로 순번을 계산
        df_display.insert(0, '순번', range(start_index + 1, start_index + 1 + len(df_display)))

    cols_to_display = ['순번'] + [col for col in display_columns_map.keys() if col in df_display.columns]
    
    df_formatted_display = df_display[cols_to_display].copy() # 필터링된 컬럼만 복사
    
    # 컬럼명 변경 (순번 컬럼은 제외)
    df_formatted_display = df_formatted_display.rename(columns={**display_columns_map, '순번': '순번'})

    # 금액 컬럼 포맷팅
    amount_cols = ['총계약금액', '금차계약금액']
    for col in amount_cols:
        if col in df_formatted_display.columns:
            # 숫자가 아닌 값(NaN, 빈 문자열 등)을 0으로 변환하고, 정수로 변환 후 콤마 포맷팅
            df_formatted_display[col] = df_formatted_display[col].apply(
                lambda x: f"{int(float(x)):,}" if pd.notnull(x) and str(x).replace('.', '').isdigit() else (
                    str(x) if str(x).strip() == '0' else '' # '0'은 '0'으로, 그 외 비정상 값은 빈칸
                )
            )

    # 데이터프레임 표시
    st.dataframe(df_formatted_display, use_container_width=True)

    # --- 페이지네이션 컨트롤 (결과 가장 하단) ---
    st.markdown("<br>", unsafe_allow_html=True) 

    current_block_index = (st.session_state.current_page - 1) // 10 
    start_page_in_block = current_block_index * 10 + 1
    end_page_in_block = min(start_page_in_block + 9, total_pages)

    page_buttons_list = []
    
    if start_page_in_block > 1:
        page_buttons_list.append(("«", start_page_in_block - 1)) 
    
    if st.session_state.current_page > 1:
        page_buttons_list.append(("⬅️", st.session_state.current_page - 1))

    for i in range(start_page_in_block, end_page_in_block + 1):
        page_buttons_list.append((str(i), i)) 
        
    if st.session_state.current_page < total_pages:
        page_buttons_list.append(("➡️", st.session_state.current_page + 1))
        
    if end_page_in_block < total_pages:
        page_buttons_list.append(("»", end_page_in_block + 1)) 

    # ★★★ 페이지 번호 버튼들을 가운데 정렬 및 동일 크기 유지 ★★★
    button_fixed_width = 0.05 
    total_occupied_width = len(page_buttons_list) * button_fixed_width
    padding_width = (1.0 - total_occupied_width) / 2 if total_occupied_width < 1.0 else 0.0

    cols_for_pages = st.columns([padding_width] + [button_fixed_width] * len(page_buttons_list) + [padding_width])
    
    for idx, (button_text, page_to_go) in enumerate(page_buttons_list):
        with cols_for_pages[idx + 1]: 
            if button_text.isdigit() and st.session_state.current_page == page_to_go: 
                if st.button(f"**{button_text}**", key=f"page_btn_{button_text}_{page_to_go}", use_container_width=True):
                    st.session_state.current_page = page_to_go
                    st.rerun()
            else:
                if st.button(button_text, key=f"page_btn_{button_text}_{page_to_go}", use_container_width=True):
                    st.session_state.current_page = page_to_go
                    st.rerun()

else:
    # 데이터가 없을 때 초기 메시지 또는 검색 결과 없음 표시
    if st.session_state.search_button_clicked:
        st.info("😅 해당 조건으로 조회된 데이터가 없습니다.")
    else:
        st.info("💡 용역명과 조회 기간을 설정하고 '검색 시작!' 버튼을 눌러주세요.")


st.markdown("---")
st.write("by.사업개발팀 😊")

