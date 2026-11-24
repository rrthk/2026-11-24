# 학교 체류 기반 출석 시스템 (초기 운영형 MVP)

관리자 웹 + 학생 Android/iOS 앱 + FastAPI 서버의 시작 프로젝트입니다.

## 포함 기능
- 학교 관리자 로그인 및 관리자 전용 수업/건물 설정
- 학생 계정 로그인
- 수업별 출석 세션 생성 및 학생 출석 체크
- 학생 앱에서 위치를 주기적으로 서버에 전송
- 서버가 수업 중 건물 반경 안/밖 체류 구간을 계산 (좌표 원본 이력은 저장하지 않고 최근 GPS 정확도와 체류 누계만 보관)
- 세션 종료 후 체류 시간 통계 및 이상치 후보 표시
- 관리자 화면에서 출석 및 이상치 후보 확인

## 중요한 운영 제한
이 프로젝트는 실제 학교 도입을 위한 **보안·기능 기반 MVP**이며, 그대로 배포해 학생 출결의 공식 증거로 사용하면 안 됩니다.
1. GPS는 실내·고층 건물·도심에서 오차가 크고 조작 가능성도 있습니다. GPS 단독으로 부정출석을 확정하지 말고 이상치 후보로만 처리하세요.
2. 현재 포함된 Flutter 앱의 위치 전송은 앱이 열린 동안 30초 간격으로 동작하는 기본 구현입니다. 백그라운드 위치 추적 서비스는 아직 구현되지 않았으며, 이를 추가하고 모바일 OS의 백그라운드 위치 권한과 실행 제한을 검증해야 합니다. 앱을 빌드한 뒤 실제 기기에서 화면 잠금, 절전 모드, 앱 강제 종료, 권한 거부, 네트워크 단절을 각각 시험해야 합니다.
3. 학교의 개인정보 보호책임자/법무 담당자 검토를 거쳐 처리 근거, 학생·보호자 고지, 보유 기간, 열람·정정 절차, 접근 통제, 파기 절차를 확정해야 합니다. 필요한 최소 위치 정보만 수집하고 수업 시간 외에는 추적하지 마세요.
4. 운영 배포 전 HTTPS, 강력한 관리자 비밀번호, 비밀키 변경, DB 백업·복구, 로그·모니터링, 취약점 점검, 침투 테스트가 필요합니다.
5. 기본 설정은 개발용 SQLite입니다. 실제 운영은 PostgreSQL과 관리형 비밀 저장소를 권장합니다.

## 1. 서버 실행 (개발 테스트)
Python 3.11 이상 권장.

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

환경변수 설정:
```bash
# Windows PowerShell
$env:JWT_SECRET="replace-with-a-long-random-secret"
$env:ADMIN_EMAIL="admin@school.example"
$env:ADMIN_PASSWORD="ChangeThis-Immediately-123!"
# macOS/Linux
export JWT_SECRET="replace-with-a-long-random-secret"
export ADMIN_EMAIL="admin@school.example"
export ADMIN_PASSWORD="ChangeThis-Immediately-123!"
```

서버 시작:
```bash
uvicorn app.main:app --reload
```
- 관리자 웹: http://127.0.0.1:8000/
- API 문서: http://127.0.0.1:8000/docs

최초 실행 시 환경변수의 관리자 계정이 생성됩니다. 기본값은 개발 편의를 위한 값이므로 운영에서 절대 사용하지 마세요.

## 2. 학생 계정 만들기
초기 MVP에서는 관리자 계정만 자동 생성됩니다. 학생은 API 문서 또는 학교의 추후 학생정보시스템 연동으로 생성해야 합니다.
`POST /admin/students` 관리자 인증 필요:
```json
{"email":"student01@school.example","password":"TempPass-12345","display_name":"학생 1"}
```

## 3. 관리자 사용 순서
1. 관리자 웹에 로그인합니다.
2. 건물 위치를 등록합니다. 위도/경도/반경을 설정합니다.
3. 수업 세션을 만듭니다. 수업 시작·종료 시각을 지정합니다.
4. 학생 앱에서 로그인 후 수업 ID를 입력하고 출석 체크합니다.
5. 학생 앱이 위치를 보고합니다.
6. 수업 종료 후 관리자 화면에서 출석과 체류시간, 이상치 후보를 확인합니다.

## 4. Flutter 앱
Flutter SDK 설치 후:
```bash
cd mobile
flutter pub get
flutter run
```
서버 주소를 `lib/config.dart`에서 변경하세요.
- Android 에뮬레이터: `http://10.0.2.2:8000`
- 실제 휴대전화: PC와 같은 네트워크에서 접근 가능한 개발 PC의 LAN IP 또는 HTTPS 서버 주소

실제 운영 앱은 반드시 서명된 빌드, 앱 배포, 권한 안내, 개인정보 처리방침, 기기별 백그라운드 테스트를 거쳐야 합니다.

## 5. 배포 권장 구성
- HTTPS를 제공하는 서버/컨테이너 플랫폼
- PostgreSQL
- 비밀키 환경변수/Secret Manager
- 관리자 계정 MFA 및 감사 로그
- 정기 백업과 복구 리허설
- 학교 SSO 또는 학생정보시스템 연동
- 최소 수집·짧은 보유기간·역할별 접근통제

## 이상치 알고리즘
세션별 체류시간(분)의 평균과 표준편차를 계산하고, 표본 수가 최소 기준 이상일 때
`|학생 체류시간 - 평균| / 표준편차 >= 임계값`이면 이상치 **후보**로 표시합니다.
이것은 통계적 편차일 뿐 부정행위 판정이 아닙니다. 조퇴, 장애, 승인된 외출, GPS 오류를 담당자가 확인해야 합니다.

## 현재 빌드의 기능 경계
- 관리자 웹과 서버 API, 계정/수업/건물 등록, 학생 출석 및 위치 핑, 서버 측 체류 누계/이상치 후보 계산이 포함됩니다.
- 학생 앱은 로그인, 출석 체크, 앱이 열린 동안 GPS 전송을 포함합니다.
- **백그라운드 위치 추적, 학생정보시스템(SSO/SIS) 연동, MFA, 비밀번호 재설정, 감사 로그, 자동 수업 종료, 실제 배포 인프라는 미완성입니다.** 이 항목을 완료하고 실기기·보안·개인정보 검증을 마쳐야 학교 운영에 사용할 수 있습니다.


## 6. 백그라운드 위치 추적 (추가된 모바일 구현)
학생 앱은 `location` Flutter 플러그인의 OS 위치 스트림을 사용합니다.
- Android: Foreground location service와 지속 알림, Android 10+ 백그라운드 위치 권한을 사용합니다. Android 11+에서는 사용자가 설정 화면에서 '항상 허용'을 별도로 선택해야 할 수 있습니다.
- iOS: `UIBackgroundModes=location` 및 When In Use/Always 사용 설명 문구가 필요합니다. 사용자는 앱 사용 중 위치 및 항상 허용 권한을 승인해야 합니다.
- 화면 잠금/다른 앱 사용 중에도 OS가 허용하는 범위에서 위치 업데이트를 받도록 설정했습니다.
- 네트워크 전송 실패 시 최대 500개 위치 이벤트를 앱 로컬에 임시 보관하고 다음 위치 이벤트 때 재전송합니다.

### 플랫폼 설정
1. Android Manifest에는 `ACCESS_BACKGROUND_LOCATION`이 선언되어 있습니다. 실제 빌드의 `targetSdk` 및 플러그인 병합 결과를 확인하고 Play Console의 위치 권한 선언을 작성하세요.
2. `mobile/ios/InfoPlist_background_location.xml` 내용을 `ios/Runner/Info.plist`의 최상위 `<dict>`에 병합하세요. Xcode의 Signing & Capabilities에서 Background Modes > Location updates를 활성화하세요.
3. iPhone은 macOS + Xcode가 있어야 빌드·서명할 수 있습니다.
4. 앱이 강제 종료되거나 OS가 프로세스를 종료하면 일반 Flutter 위치 스트림은 지속된다고 보장할 수 없습니다. 이 앱은 강제 종료 후 자동 재시작을 보장하지 않습니다.
5. iOS는 업데이트 주기와 전달 시점을 OS가 결정합니다. '30초마다 정확히'를 보장하지 않습니다.
6. 실제 운영 전 최소한 Android 10~15, iOS 최신/직전 버전, 화면 잠금, 절전, 저전력 모드, 실내·실외, 권한 철회, 앱 스와이프 종료, 네트워크 끊김을 시험하세요.
