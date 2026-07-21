# ISSEY MIYAKE 한국어 카탈로그·주문 보조 v2 초안

기존 SPECIAL PRICE 카탈로그를 확장한 테스트 버전입니다.

## 이번 버전에 들어간 기능

- 로그인된 브라우저 프로필을 이용한 전체 상품 API 수집
- 전체 상품 API 실패 시 설정된 컬렉션 페이지 링크 수집
- 상품명 한국어 번역 및 번역 결과 캐시
- 일본 판매가(JPY)와 예상 원화가(KRW) 동시 표시
- 계산식: `JPY × JPY/KRW 환율 × 1.04 + 25,000원`
- 기본 1,000원 단위 올림
- 상품 사진·설명·옵션별 재고·SKU·サイズチャート
- 주문 요청 내용 자동 생성 및 복사
- 견적 문의 링크 연결
- 공식 상품페이지 실제 재고 확인 링크
- 로그인된 브라우저로 공식 상품페이지를 여는 구매 보조 기능
- GitHub Pages 자동 게시

> 자동 장바구니 추가, PayPal 로그인, 결제 승인, 최종 주문 확정은 포함하지 않았습니다. 구매 보조창에서 사용자가 실제 재고와 가격을 확인한 뒤 직접 결제해야 합니다.

---

## 1. 새 폴더에 압축 풀기

권장 경로:

```text
D:\issey_korea_order_assistant_v2
```

기존 v1.2 폴더 위에 덮어쓰지 말고 새 폴더를 사용하세요.

기존 로그인 상태를 재사용하려면 기존 폴더의 다음 폴더를 새 프로젝트로 복사할 수 있습니다.

```text
기존 폴더\private\browser_profile
→ 새 폴더\private\browser_profile
```

로그인 프로필을 복사하지 않아도 `02_LOGIN.bat`에서 다시 로그인하면 됩니다.

---

## 2. 설치

Python 3.12 일반 버전이 없다면 먼저 실행합니다.

```text
00_INSTALL_PYTHON_312.bat
```

그다음:

```text
01_INSTALL.bat
```

설치되는 패키지:

- Playwright
- Chromium
- deep-translator

Python 3.13 free-threaded 빌드는 사용하지 않습니다.

---

## 3. 로그인 저장

```text
02_LOGIN.bat
```

1. 열린 브라우저에서 직접 로그인합니다.
2. 상품 목록과 상세페이지가 정상적으로 보이는지 확인합니다.
3. 검은 창으로 돌아와 Enter를 누릅니다.

아이디·비밀번호는 코드나 GitHub에 저장되지 않습니다.

---

## 4. Google 기준환율 설정

### Google Sheets 만들기

Google Sheets의 A1 셀에 입력합니다.

```text
=GOOGLEFINANCE("CURRENCY:JPYKRW")
```

시트에 환율 숫자가 표시되면 시트를 웹에서 읽을 수 있는 CSV 주소로 설정합니다.

예시 형식:

```text
https://docs.google.com/spreadsheets/d/시트ID/gviz/tq?tqx=out:csv&sheet=시트이름
```

필요한 경우 Google Sheets 공유 설정을 `링크가 있는 사용자 보기`로 설정해야 합니다. 개인정보가 들어 있지 않은 환율 전용 시트를 따로 쓰는 것을 권장합니다.

`config.json`에서 아래 값을 변경합니다.

```json
"pricing": {
  "google_sheet_csv_url": "여기에 CSV 주소",
  "manual_jpy_krw": 9.30,
  "markup_percent": 4.0,
  "fixed_fee_krw": 25000,
  "round_unit": 1000,
  "round_mode": "ceil"
}
```

Google Sheets 조회가 실패하면 마지막 정상 환율을 사용합니다. 정상 환율 기록이 없으면 `manual_jpy_krw`를 사용합니다.

### 가격 계산

```text
예상 원화가 = JPY 가격 × 환율 × 1.04 + 25,000원
```

기본값은 1,000원 단위 올림입니다.

```json
"round_unit": 1000,
"round_mode": "ceil"
```

`round_mode` 값:

- `ceil`: 올림
- `round`: 반올림
- `floor`: 내림

---

## 5. 전체 상품 수집 테스트

```text
03_TEST_COLLECTION.bat
```

수집 성공 후 `index.html`이 열립니다.

로컬에서 링크 이동이나 복사 기능을 더 안정적으로 확인하려면:

```text
08_OPEN_LOCAL_SITE.bat
```

브라우저에서 아래 주소가 열립니다.

```text
http://127.0.0.1:8765/
```

### 첫 실행이 오래 걸리는 이유

전체 상품의 상세페이지와 サイズチャート를 한 번에 모두 열지 않도록 기본 제한을 두었습니다.

```json
"max_new_detail_pages_per_run": 25
```

첫 실행에서 25개 상세페이지를 확인하고, 다음 실행에서 나머지를 이어서 확인합니다. 빠르게 채우려면 값을 늘릴 수 있지만 사이트 요청량도 함께 늘어납니다.

---

## 6. 한국어 번역 설정

기본 설정:

```json
"translation": {
  "enabled": true,
  "translate_descriptions": false,
  "max_new_translations_per_run": 30
}
```

- 상품명은 한국어 번역을 시도합니다.
- 번역 결과는 `private/translation_cache.json`에 저장됩니다.
- 한 실행당 신규 번역 30개까지 처리합니다.
- 설명까지 번역하려면 `translate_descriptions`를 `true`로 변경합니다.

번역 서비스 호출이 실패하면 일본어 원문을 그대로 표시하고 다음 실행에서 다시 시도할 수 있습니다.

---

## 7. 주문 요청 흐름

1. 상품 상세페이지에서 재고 옵션을 선택합니다.
2. `색상·사이즈 선택 후 주문 요청`을 누릅니다.
3. 주문 요청서에서 이름·연락처·수량·요청사항을 입력합니다.
4. `주문 요청 내용 복사`를 누릅니다.
5. `복사 후 견적 문의 열기`를 누르면 다음 페이지가 열립니다.

```text
https://blog.naver.com/pilkyu01/224353040280
```

주문 요청서에는 다음 정보가 자동으로 포함됩니다.

- 한국어 상품명
- 일본어 원문
- 상품번호
- 선택 색상·사이즈
- SKU
- JPY 가격
- 예상 KRW 가격
- 적용 환율
- 자체 상세페이지 링크
- 공식 상품페이지 링크

GitHub Pages만으로는 고객정보를 안전하게 서버에 저장할 수 없기 때문에, 이번 초안은 주문 내용을 복사해서 문의하는 구조입니다.

---

## 8. 공식 구매 보조창

관리자 PC에서 실행합니다.

```text
09_PURCHASE_ASSISTANT.bat
```

입력 항목:

```text
Product handle or product ID
Variant title, size, SKU, or variant ID
```

구매 보조창은 로그인된 브라우저에서 공식 상품페이지를 열고 다음 내용을 터미널에 보여줍니다.

- 고객이 선택한 상품
- 옵션
- 마지막 수집 재고
- 예상 원화가

그다음 사용자가 공식 사이트에서 직접 확인하고 PayPal 결제를 진행합니다.

다음 동작은 자동으로 하지 않습니다.

- 장바구니 자동 추가
- PayPal 로그인
- PayPal 비밀번호 저장
- 2단계 인증
- 결제 승인
- 최종 주문 확정

---

## 9. GitHub 연결

먼저 Git for Windows를 설치합니다.

```powershell
winget install --id Git.Git -e --source winget
```

GitHub에서 빈 Public 저장소를 만든 뒤:

```text
04_CONNECT_GITHUB.bat
```

저장소 주소와 사용할 GitHub 계정을 입력합니다.

다른 계정으로 403 오류가 발생하면 Windows `자격 증명 관리자`에서 다음 항목을 제거한 뒤 다시 실행하세요.

```text
git:https://github.com
```

GitHub 저장소에서:

```text
Settings → Pages
Source: Deploy from a branch
Branch: main
Folder: /(root)
```

---

## 10. 자동 업데이트

자동 수집과 GitHub 게시:

```text
05_START_CATALOG_SYNC.bat
```

한 번만 수집하고 게시:

```text
06_UPDATE_AND_PUBLISH_ONCE.bat
```

Windows 로그인 시 자동 시작:

```text
10_INSTALL_AUTOSTART.bat
```

자동 시작 제거:

```text
11_REMOVE_AUTOSTART.bat
```

전체 사이트이므로 기본 갱신 간격은 15분입니다.

```json
"refresh_minutes": 15
```

---

## 11. 전체 상품이 모두 수집되지 않을 때

기본적으로 먼저 다음 전체 상품 API를 시도합니다.

```text
https://www.isseymiyake.com/products.json
```

그리고 SPECIAL PRICE API도 합쳐서 중복을 제거합니다.

```text
https://www.isseymiyake.com/collections/special-price/products.json
```

사이트 구조상 전체 상품 API에서 일부 상품이 빠진다면 `config.json`의 `product_json_urls` 또는 `collection_urls`에 브랜드별 컬렉션 주소를 추가하세요.

예시:

```json
"collection_urls": [
  "https://www.isseymiyake.com/collections/special-price",
  "https://www.isseymiyake.com/collections/추가할-컬렉션"
]
```

이 부분은 실제 첫 수집 결과를 보고 수정할 예정입니다.

---

## 12. 공개되지 않는 정보

다음 정보는 `.gitignore`로 GitHub 업로드에서 제외됩니다.

```text
private/browser_profile/
private/translation_cache.json
private/debug_collection.html
private/debug_collection.png
private/debug_info.json
.venv/
```

이번 초안은 고객 주문정보를 파일이나 GitHub에 자동 저장하지 않습니다.

---

## 13. 진단

```text
07_DIAGNOSE.bat
```

진단 파일:

```text
private/debug_collection.html
private/debug_collection.png
private/debug_info.json
```

수집 오류가 발생하면 검은 창의 오류 내용과 위 진단 파일을 확인하면 됩니다.

---

## 현재 초안에서 실제 확인이 필요한 부분

사용자의 로그인 세션이 없는 환경에서는 다음 항목을 실제 검증할 수 없습니다.

- 전체 `/products.json`이 로그인 후 몇 개 상품을 반환하는지
- 브랜드별 컬렉션 누락 여부
- 상품 옵션에서 색상과 사이즈가 어떤 순서로 제공되는지
- 일부 상품의 サイズチャート HTML 구조
- Google Sheets CSV 주소 형식과 값 위치
- 한국어 번역 품질

따라서 먼저 `03_TEST_COLLECTION.bat`을 실행하고 생성된 `data/catalog.json`과 오류 로그를 기준으로 다음 버전을 수정하는 방식이 가장 빠릅니다.
