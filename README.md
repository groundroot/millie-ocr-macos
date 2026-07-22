# Millie OCR for macOS

밀리의서재에서 사용자가 열어 둔 책을 한 장씩 캡처하고 Mac에서 OCR하여 다음 결과를 만드는 자동화입니다.

- 원본 화면을 보존한 검색 가능한 PDF
- 페이지 번호와 구분선 없이 본문이 이어지는 Markdown
- 글자 크기를 조절할 수 있는 EPUB 3 전자책
- 준비부터 검증까지 단계별 퍼센트를 보여 주는 로컬 대시보드

캡처 이미지와 OCR 결과는 사용자의 Mac 안에서 처리됩니다. 이 프로젝트에는 책 파일, 캡처 이미지, OCR 결과 또는 DRM 해제 기능이 포함되어 있지 않습니다.

> 본인이 소유했거나 복제·OCR에 명시적인 허가를 받은 자료에만 사용하세요. 서비스 이용약관과 해당 지역의 저작권법을 확인할 책임은 사용자에게 있습니다.

## 한 줄 설치

터미널을 열고 다음 명령을 한 번 실행합니다.

```bash
/bin/zsh -c "$(curl -fsSL https://raw.githubusercontent.com/groundroot/millie-ocr-macos/main/bootstrap_macos.sh)"
```

이 명령은 Homebrew가 없으면 먼저 설치하고, Python·Poppler·llama.cpp·Git을 준비한 뒤 Millie OCR를 설치합니다. Homebrew 설치 중 macOS 관리자 암호를 요청할 수 있습니다.

앱 설치와 서명이 끝나면 다음 권한 화면이 순서대로 자동으로 열립니다.

1. **손쉬운 사용:** 목록에서 `밀리 OCR`을 켜고 앱의 **권한 확인**을 누릅니다.
2. **화면 및 시스템 오디오 녹음:** `밀리 OCR`을 켜고 다시 **권한 확인**을 누릅니다.
3. 설치기가 두 승인을 실제로 확인한 뒤 나머지 설치를 완료합니다.

macOS 보안 정책상 설치기가 스위치를 대신 켤 수는 없습니다. 설정 화면 열기, 앱 등록, 승인 확인과 다음 단계 이동은 자동이며 사용자는 `밀리 OCR` 스위치만 직접 켜면 됩니다. 권한 대상은 `밀리의서재`가 아닙니다.

설치되는 주요 위치:

```text
~/Applications/밀리 OCR.app
~/Library/Application Support/MillieOCR/
```

별도의 화면 제어 앱은 필요하지 않습니다. 페이지 확인과 키 입력은 macOS의 손쉬운 사용 기능으로, 창 캡처는 CoreGraphics로 처리합니다.

## 단축어 만들기

1. macOS **단축어** 앱에서 새 단축어를 만들고 이름을 `밀리 OCR`로 지정합니다.
2. **앱 열기** 동작을 추가합니다.
3. 앱으로 `밀리 OCR`을 선택합니다. 목록에 없다면 **기타**에서 `~/Applications/밀리 OCR.app`을 고릅니다.
4. 단축어를 저장합니다.

기존에 **AppleScript 실행** 방식으로 만든 단축어가 있다면 [Shortcut_Action.applescript](Shortcut_Action.applescript)의 최신 내용으로 교체해도 됩니다.

## 처음 한 번만 권한 설정

설치 과정에서 손쉬운 사용과 화면 녹화 권한을 순서대로 확인합니다. 나중에 권한을 끄거나 캡처가 시작되지 않으면 **시스템 설정 → 개인정보 보호 및 보안**에서 다음 항목을 확인하세요.

> **중요:** 권한을 허용할 대상은 `밀리의서재`가 아니라 `밀리 OCR`입니다. 밀리의서재에만 권한을 줘서는 페이지를 제어할 수 없습니다.

- **손쉬운 사용:** `밀리 OCR` 허용. AppleScript 실행 단축어를 쓴다면 `단축어`도 허용
- **화면 및 시스템 오디오 녹음:** `밀리 OCR` 허용. AppleScript 실행 단축어를 쓴다면 `단축어`도 허용
- **자동화:** 첫 OCR 실행에서 요청하면 `밀리 OCR` 또는 `단축어`가 `System Events`와 밀리의서재를 제어하도록 허용
- **파일 및 폴더:** 선택한 저장 폴더 접근 허용

권한을 바꾼 뒤에는 밀리 OCR과 단축어를 종료했다가 다시 실행하세요.

`밀리 OCR`은 캡처가 끝날 때까지 실행 상태를 유지해야 손쉬운 사용 권한이 페이지 제어 명령에 이어집니다. Dock이나 강제 종료 창에서 작업 중인 `밀리 OCR`을 종료하지 마세요.

## 실행 방법

1. 밀리의서재 앱에서 처리할 책을 한 페이지 보기로 엽니다.
2. 메뉴나 설정 팝업을 닫고 `밀리 OCR` 단축어를 실행합니다.
3. 가장 먼저 나타나는 폴더 선택 창에서 결과를 저장할 위치를 고릅니다.
4. 브라우저에서 열리는 대시보드로 진행률을 확인합니다.
5. 캡처가 끝날 때까지 마우스·키보드를 사용하거나 다른 앱으로 전환하지 않습니다.

선택한 폴더 안에 `책제목_YYYYMMDD_HHMMSS` 실행 폴더가 만들어지며, 이미지·PDF·Markdown·EPUB·검증 파일이 모두 그 안에 저장됩니다. 저장 위치는 실행할 때마다 다르게 선택할 수 있습니다.

대시보드 주소:

```text
http://127.0.0.1:8765
```

작업 중에는 Mac이 잠들거나 화면이 꺼지지 않도록 자동으로 유지합니다. 페이지 이동 전에는 밀리의서재를 다시 전면으로 가져오므로 일시적인 포커스 손실은 재시도하지만, 안전한 캡처를 위해 작업 중 입력은 피하세요.

## 처리 순서

1. 사용자가 결과 저장 폴더 선택
2. 열린 밀리의서재 책과 현재 쪽수 확인
3. 첫 페이지로 이동
4. 마지막 페이지까지 고속 캡처
5. Surya 한국어 OCR 및 검색 가능한 PDF 생성
6. 페이지 번호 없는 연속 Markdown 생성
7. EPUB 3 생성
8. 이미지 수·PDF 쪽수·한글 텍스트·첫 장·중간 장·마지막 장 검증

전체 쪽수를 제공하지 않는 뷰어에서는 페이지 슬라이더와 마지막 장에서의 반복 정지를 이용해 종료 지점을 확인합니다. 이 경우 마지막 장이 확인될 때 캡처 진행률이 100%가 됩니다.

## 결과 구성

```text
선택한 폴더/책제목_YYYYMMDD_HHMMSS/
├── images/                       A5 1748 × 2480 PNG 페이지
├── surya-results/results.json    OCR 원본 결과
├── validation/                   텍스트 및 렌더링 검증 자료
├── 책제목_Surya2_OCR.pdf          검색 가능한 PDF
├── 책제목_extracted.md            페이지 번호 없는 연속 Markdown
├── 책제목_extracted.epub          리플로우 가능한 EPUB 3
└── capture_manifest.json         캡처 쪽수와 파일 해시
```

CoreGraphics로 해당 창만 임시 JPEG로 캡처하고, A5 크기의 최종 PNG 변환은 다음 페이지 이동과 병렬 처리합니다. 캡처 중 손쉬운 사용 정보는 전체 UI 트리 대신 페이지 카운터만 읽는 고속 경로를 사용합니다. 각 페이지의 번호 증가와 중복 화면을 확인하므로 건너뛰기나 정지가 감지되면 잘못된 결과 생성을 중단합니다.

## 문제 해결

### 폴더 선택 창 이후 캡처가 시작되지 않음

- 밀리의서재에서 실제 책 본문을 한 페이지 보기로 열었는지 확인합니다.
- 목차, 설정, 완료 팝업을 닫습니다.
- `밀리 OCR`의 손쉬운 사용과 화면 녹화 권한을 확인합니다.
- 외장 디스크나 네트워크 폴더라면 쓰기 권한과 연결 상태를 확인합니다.

상태 파일의 오류가 `osascript에 보조 접근이 허용되지 않습니다 (-25211)`라면 최신 버전을 다시 설치한 뒤, 손쉬운 사용 목록에서 기존 `밀리 OCR`을 제거하고 `~/Applications/밀리 OCR.app`을 다시 추가하세요. 앱 식별자는 `com.groundroot.millieocr`입니다.

실행 기록:

```text
~/Library/Logs/MillieOCRShortcut.log
```

### 대시보드가 열리지 않음

```bash
launchctl kickstart -k "gui/$(id -u)/com.millieocr.dashboard"
open http://127.0.0.1:8765
```

대시보드 기록:

```text
~/Library/Logs/MillieOCRDashboard.log
```

### OCR 엔진 설치 실패

```bash
brew install python poppler llama.cpp
"$HOME/Library/Application Support/MillieOCR/install_surya_macos.sh" --python "$(command -v python3)"
```

첫 OCR 실행은 Surya 모델을 내려받기 때문에 오래 걸릴 수 있습니다.

## 수동 설치

```bash
git clone https://github.com/groundroot/millie-ocr-macos.git
cd millie-ocr-macos
./bootstrap_macos.sh
```

화면이 없는 원격 설치나 개발 검증에서만 권한 설정 단계를 건너뛰려면 `MILLIE_OCR_SKIP_PERMISSION_SETUP=1`을 사용할 수 있습니다. 일반 사용자는 건너뛰지 마세요.

## 제거

```bash
launchctl bootout "gui/$(id -u)/com.millieocr.dashboard" 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.millieocr.dashboard.plist
rm -rf "$HOME/Library/Application Support/MillieOCR"
rm -rf "$HOME/Applications/밀리 OCR.app"
```

OCR 모델 캐시와 사용자가 선택한 결과 폴더는 자동 삭제하지 않습니다.

## 라이선스와 외부 구성요소

이 저장소의 코드는 [MIT License](LICENSE)로 배포합니다.

- [Surya](https://github.com/datalab-to/surya) 코드는 Apache-2.0입니다.
- Surya 모델 가중치는 별도의 수정 OpenRAIL-M 조건이 적용됩니다. 최신 사용 조건은 Surya 저장소를 확인하세요.
- 밀리의서재는 해당 권리자의 상표입니다. 이 프로젝트는 밀리의서재와 제휴하거나 공식 승인받은 프로젝트가 아닙니다.

## 개발 검증

```bash
python3 -m py_compile *.py
zsh -n run_millie_ocr.sh install_local.sh bootstrap_macos.sh
osacompile -o /tmp/millie_native.scpt millie_native.applescript
```
