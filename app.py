import streamlit as st
import os
import requests
import wikipediaapi
from googleapiclient.discovery import build
import json
import time
import shutil # 폴더 압축용
import base64

# ==========================================
# [설정] 🔑 API 키 (여기에 입력하세요)
# ==========================================
# 스트림릿의 비밀 금고(secrets)에서 키를 가져옵니다.
# 만약 금고에 키가 없으면(내 PC에서 돌릴 때), 오류 방지를 위해 빈 문자열을 넣습니다.
if "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    GOOGLE_SEARCH_ENGINE_ID = st.secrets["GOOGLE_SEARCH_ENGINE_ID"]
    EMUSEUM_API_KEY = st.secrets["EMUSEUM_API_KEY"]
else:
    # 내 PC에서 테스트할 때를 위해 기존 키를 여기에 적어둘 수도 있습니다.
    # 하지만 배포할 때는 이 부분을 비워두거나 주의해야 합니다.
    GOOGLE_API_KEY = "여기에_원래_키를_적어도_되지만_추천하지_않음"
    GOOGLE_SEARCH_ENGINE_ID = "여기에_원래_키"
    EMUSEUM_API_KEY = "여기에_원래_키"
    
# [설정] 검색 수량
COUNT_WIKIMEDIA = 10
COUNT_THE_MET = 5
COUNT_GOOGLE = 3

# ==========================================
# [기능] Streamlit 전용 함수들
# ==========================================
def create_temp_folder(folder_name):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
    # 기존 파일 삭제 (깨끗한 시작)
    for filename in os.listdir(folder_name):
        file_path = os.path.join(folder_name, filename)
        try:
            if os.path.isfile(file_path): os.unlink(file_path)
        except: pass

def save_text_file(folder_name, filename, content):
    with open(os.path.join(folder_name, filename), "w", encoding="utf-8") as f:
        f.write(content)

# ==========================================
# [수정] 확장자 자동 보정 다운로더
# ==========================================
def download_image(url, folder_name, filename, source_list, visited_urls):
    # 1. 중복 및 URL 유효성 체크
    if url in visited_urls: return False
    if not url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')): return False

    # [핵심 수정] 파일명에 확장자(.jpg 등)가 없으면 강제로 붙여줍니다!
    if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
        filename += ".jpg"

    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            path = os.path.join(folder_name, filename)
            with open(path, 'wb') as f: f.write(response.content)
            
            source_list.append(f"[{filename}] : {url}")
            visited_urls.add(url)
            return True
    except: pass
    return False

def get_english_name_from_wiki(korean_name):
    wiki = wikipediaapi.Wikipedia(user_agent='HistoryApp/1.0', language='ko')
    page = wiki.page(korean_name)
    if page.exists() and 'en' in page.langlinks:
        return page.langlinks['en'].title
    return None

# ==========================================
# [검색 소스 함수들] (기존 로직 동일, print 대신 st.write 사용 안함)
# ==========================================
def run_search_logic(name, folder_name, use_met, use_google, progress_bar):
    visited_urls = set()
    source_list = []
    
    # 1. 위키백과
    progress_bar.progress(10, text="📖 위키백과 정보 수집 중...")
    wiki = wikipediaapi.Wikipedia(user_agent='HistoryApp/1.0', language='ko')
    page = wiki.page(name)
    if page.exists():
        content = f"인물: {name}\nURL: {page.fullurl}\n\n{page.text}"
        save_text_file(folder_name, f"01_{name}_상세정보.txt", content)

    # 2. 영문명 탐색
    progress_bar.progress(20, text="🔤 영문 이름 변환 중...")
    english_name = get_english_name_from_wiki(name)
    search_name_global = english_name if english_name else name
    
    # 3. 위키미디어
    progress_bar.progress(30, text="🌍 위키미디어 이미지 검색 중...")
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"File:{search_name_global}", "gsrnamespace": 6, 
        "gsrlimit": COUNT_WIKIMEDIA, "prop": "imageinfo", "iiprop": "url"
    }
    try:
        res = requests.get(url, params=params, headers={'User-Agent': 'Bot/App'}).json()
        if "query" in res:
            for page_id in res["query"]["pages"]:
                item = res["query"]["pages"][page_id]
                if "imageinfo" in item:
                    img_url = item["imageinfo"][0]["url"]
                    title = item['title'].replace("File:", "").replace(" ", "_")[:20]
                    safe = "".join(c for c in title if c.isalnum() or c in ('_','.'))
                    download_image(img_url, folder_name, f"Wiki_{safe}", source_list, visited_urls)
    except: pass

    # 4. e뮤지엄
    if EMUSEUM_API_KEY and "여기에" not in EMUSEUM_API_KEY:
        progress_bar.progress(50, text="🏺 e뮤지엄 유물 검색 중...")
        base_url = "http://www.emuseum.go.kr/openapi/relic/list"
        request_url = f"{base_url}?serviceKey={EMUSEUM_API_KEY}&name={name}&numOfRows=10"
        try:
            res = requests.get(request_url).json()
            items = res.get('list', [])
            info_text = ""
            for i, item in enumerate(items):
                title = item.get('name', '무제')
                desc = item.get('desc', '설명 없음')
                info_text += f"[{i+1}] {title} : {desc}\n"
                if item.get('imgUrl'):
                    img = "http://www.emuseum.go.kr" + item['imgUrl'] if not item['imgUrl'].startswith('http') else item['imgUrl']
                    safe = "".join(c for c in title if c.isalnum())[:10]
                    download_image(img, folder_name, f"eMuseum_{i}_{safe}.jpg", source_list, visited_urls)
            if info_text: save_text_file(folder_name, f"02_{name}_e뮤지엄.txt", info_text)
        except: pass

    # 5. 메트로폴리탄 (선택)
    if use_met:
        progress_bar.progress(70, text="🏛️ 메트로폴리탄 미술관 검색 중...")
        q_name = english_name if english_name else name
        try:
            res = requests.get("https://collectionapi.metmuseum.org/public/collection/v1/search", 
                               params={"q": q_name, "hasImages": "true", "isOnView": "true"}).json()
            ids = res.get('objectIDs', [])
            count = 0
            for obj_id in ids:
                if count >= COUNT_THE_MET: break
                try:
                    item = requests.get(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{obj_id}").json()
                    img_url = item.get('primaryImage')
                    if img_url and img_url not in visited_urls:
                        title = "".join(c for c in item.get('title','T') if c.isalnum())[:10]
                        if download_image(img_url, folder_name, f"Met_{obj_id}_{title}.jpg", source_list, visited_urls):
                            count += 1
                except: continue
        except: pass

    # 6. 구글 (선택)
    if use_google and GOOGLE_API_KEY and "여기에" not in GOOGLE_API_KEY:
        progress_bar.progress(85, text="🔎 구글 상세 검색 중...")
        queries = [name] + [f"{name} {kw}" for kw in ["업적", "Inventions", "Work"]]
        service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
        for q in queries:
            try:
                res = service.cse().list(q=q, cx=GOOGLE_SEARCH_ENGINE_ID, searchType='image', num=COUNT_GOOGLE, safe='active').execute()
                if 'items' in res:
                    for i, item in enumerate(res['items']):
                        download_image(item['link'], folder_name, f"Google_{q}_{i}.jpg", source_list, visited_urls)
            except: pass

    # 마무리
    progress_bar.progress(100, text="완료!")
    
    # 출처 파일 저장
    with open(os.path.join(folder_name, "00_출처.txt"), "w", encoding="utf-8") as f:
        for item in source_list: f.write(f"{item}\n")
        
    return source_list

# ==========================================
# [화면] Streamlit UI 구성
# ==========================================
def main():
    st.set_page_config(page_title="역사 인물 아카이브", page_icon="🏛️")
    
    st.title("🏛️ 역사 인물 마스터 AI")
    st.markdown("인물 이름을 입력하면 **위키, e뮤지엄, 메트로폴리탄, 구글**을 모두 검색하여 정리해줍니다.")

    with st.form("search_form"):
        name = st.text_input("찾을 인물 이름 (예: 세종대왕, 반 고흐)", "")
        
        col1, col2 = st.columns(2)
        with col1:
            use_met = st.checkbox("🏛️ 메트로폴리탄 검색 (예술가/고대)", value=False)
        with col2:
            use_google = st.checkbox("🔎 구글 검색 추가 (업적 포함)", value=True)
            
        submitted = st.form_submit_button("🔍 검색 시작 (Start)")

    if submitted and name:
        folder_name = "temp_result" # 임시 폴더
        create_temp_folder(folder_name)
        
        progress_bar = st.progress(0, text="준비 중...")
        
        # 검색 실행!
        source_list = run_search_logic(name, folder_name, use_met, use_google, progress_bar)
        
        st.success(f"🎉 수집 완료! 총 {len(source_list)}개의 자료를 찾았습니다.")
        
        # 1. 갤러리 보여주기
        st.subheader("🖼️ 수집된 이미지 미리보기")
        images = [f for f in os.listdir(folder_name) if f.endswith(('.jpg', '.png'))]
        if images:
            st.image([os.path.join(folder_name, img) for img in images[:9]], width=100, caption=images[:9])
            if len(images) > 9:
                st.info(f"...외 {len(images)-9}장 더 있음")

        # 2. 압축 파일 다운로드 버튼 (폰에서 가장 중요한 기능)
        shutil.make_archive(f"{name}_자료모음", 'zip', folder_name)
        
        with open(f"{name}_자료모음.zip", "rb") as fp:
            st.download_button(
                label="📦 전체 자료 다운로드 (ZIP)",
                data=fp,
                file_name=f"{name}_자료모음.zip",
                mime="application/zip"
            )

if __name__ == "__main__":
    main()