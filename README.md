# Millie OCR for macOS

밀리의서재에서 사용자가 열어 둔 책을 한 장씩 캡처하고, 로컬 Surya OCR로 다음 결과를 만드는 macOS 자동화입니다.

- 원본 화면을 보존한 검색 가능한 PDF
- 페이지 번호와 구분선 없이 본문이 이어지는 Markdown
- 글자 크기를 조절할 수 있는 EPUB 3 전자책
- 준비부터 검증까지 단계별 퍼센트를 보여 주는 로컬 대시보드

모든 이미지와 OCR 결과는 사용자의 Mac 안에서 처리됩니다. 이 프로젝트에는 책 파일, 캡처 이미지, OCR 결과 또는 DRM 해제 기능이 포함되어 있지 않습니다.

> 본인이 소유했거나 복제·OCR에 명시적인 허가를 받은 자료에만 사용하세요. 서비스 이용약관과 해당 지역의 저작권법을 확인할 책임은 사용자에게 있습니다.

## 지원 환경

- macOS
- 밀리의서재 macOS 앱
- [Homebrew](https://brew.sh/)
- Python 3.10 이상
- [Orca](https://www.onorca.dev/docs/install) 앱과 `orca` CLI
- 여유 저장 공간: 책 한 권당 캡처 이미지와 OCR 모델을 포함해 수 GB를 권장

개발과 검증은 Apple Silicon Mac에서 진행했습니다. Intel Mac에서도 Orca와 Python·Surya 의존성이 설치되면 동작하도록 작성되어 있지만 별도 실기 검증은 하지 않았습니다.

## 1. 필수 도구 설치

터미널에서 다음 명령을 실행합니다.

```bash
brew install python poppler llama.cpp
brew install --cask stablyai/orca/orca
```

Orca를 한 번 실행한 뒤 `orca` 명령이 없으면 Orca의 **Settings → General → Orca CLI**에서 CLI를 설치합니다.

```bash
orca status
```

## 2. Millie OCR 설치

```bash
git clone https://github.com/groundroot/millie-ocr-macos.git
cd millie-ocr-macos
./install_local.sh
```

설치 위치는 다음과 같습니다.

```text
~/Library/Application Support/MillieOCR/
```

설치 과정에서 로컬 대시보드를 로그인 후 계속 실행하는 사용자 서비스도 함께 등록됩니다.

## 3. macOS 권한 설정

처음 사용할 때 macOS가 요청하는 권한을 허용합니다. 권한이 나타나지 않거나 캡처가 시작되지 않으면 **시스템 설정 → 개인정보 보호 및 보안**에서 확인하세요.

- **손쉬운 사용:** Orca, 단축어
- **화면 및 시스템 오디오 녹음:** Orca, 단축어
- **자동화:** 단축어가 밀리의서재를 제어하도록 허용
- **파일 및 폴더:** 단축어의 문서 폴더 접근 허용

권한을 변경했다면 Orca, 단축어, 밀리의서재를 모두 종료했다가 다시 실행하는 것이 안전합니다.

## 4. 단축어 만들기

1. macOS **단축어** 앱을 엽니다.
2. 새 단축어를 만들고 이름을 `밀리 OCR`로 지정합니다.
3. **AppleScript 실행** 동작을 추가합니다.
4. [Shortcut_Action.applescript](Shortcut_Action.applescript)의 내용을 전부 붙여 넣습니다.
5. 단축어를 저장합니다.

AppleScript 편집기에서 직접 실행하려면 설치 폴더의 `Millie_OCR.scpt`를 사용할 수도 있습니다.

## 5. OCR 실행

1. 밀리의서재에서 처리할 책을 엽니다.
2. 한 페이지 보기 상태로 두고 메뉴나 목차를 닫습니다.
3. 단축어 앱이나 Spotlight에서 **밀리 OCR**을 실행합니다.
4. 브라우저에서 열리는 대시보드를 확인합니다.
5. 캡처가 끝날 때까지 마우스·키보드를 사용하거나 다른 앱으로 전환하지 않습니다.

대시보드 주소:

```text
http://127.0.0.1:8765
```

Mac이 잠자지 않도록 작업 중에는 자동으로 `caffeinate`가 적용됩니다. 알림이나 창 전환으로 밀리의서재가 포커스를 잃으면 자동으로 창을 복구하고 페이지 넘김을 재시도합니다.

## 처리 순서

1. 열린 밀리의서재 책과 창 확인
2. 첫 페이지로 이동
3. 마지막 페이지까지 고속 캡처
4. Surya 한국어 OCR
5. 검색 가능한 PDF 생성
6. 연속 Markdown 생성
7. EPUB 3 생성
8. 이미지 수·PDF 쪽수·한글 텍스트·첫 장·중간 장·마지막 장 검증

새 밀리 뷰어처럼 전체 쪽수를 제공하지 않는 화면은 페이지 슬라이더와 마지막 장에서의 반복 정지를 이용해 종료 지점을 찾습니다. 이 경우 캡처 중 정확한 퍼센트는 계산할 수 없어 현재 쪽수가 표시되고, 마지막 장 확인 후 100%가 됩니다.

## 고속 캡처 방식

- Orca의 접근성 창 번호와 macOS CoreGraphics 창 번호를 따로 확인합니다.
- 실제 CoreGraphics 창 번호로 해당 창만 직접 캡처합니다.
- 임시 화면은 JPEG로 받아 호출 시간과 임시 용량을 줄입니다.
- 최종 페이지는 A5 300dpi 기준 `1748 × 2480` 무손실 PNG로 저장합니다.
- 이미지 리사이즈와 PNG 저장은 다음 페이지 이동과 병렬 처리합니다.
- 매 페이지의 번호 증가와 중복 화면을 확인하므로 건너뛰기나 정지가 감지되면 결과 생성을 중단합니다.

로컬 대시보드 창을 대상으로 한 7회 평균 측정에서 Orca 스크린샷은 약 0.621초, CoreGraphics 직접 캡처는 약 0.182초였습니다. 임시 JPEG 사용 시 약 0.147초까지 줄었습니다. 실제 책의 속도는 밀리 뷰어 렌더링, 창 크기, Mac 성능에 따라 달라집니다.

## 결과 위치

기본 결과 폴더:

```text
~/Documents/Codex/OCR Results/책제목_YYYYMMDD_HHMMSS/
```

각 실행 폴더에는 다음 항목이 만들어집니다.

```text
images/                       캡처된 A5 PNG 페이지
surya-results/results.json    Surya OCR 원본 결과
validation/                   텍스트 및 렌더링 검증 자료
책제목_Surya2_OCR.pdf          검색 가능한 PDF
책제목_extracted.md            페이지 번호 없는 연속 Markdown
책제목_extracted.epub          리플로우 가능한 EPUB 3
capture_manifest.json         캡처 쪽수와 파일 해시
```

## 문제 해결

### 대시보드가 열리지 않음

```bash
launchctl kickstart -k "gui/$(id -u)/com.millieocr.dashboard"
open http://127.0.0.1:8765
```

대시보드 로그:

```text
~/Library/Logs/MillieOCRDashboard.log
```

### 캡처가 시작되지 않음

- 밀리의서재에서 실제 책 본문을 한 페이지 보기로 열었는지 확인합니다.
- 목차, 설정, 완료 팝업을 닫습니다.
- `orca status`가 정상인지 확인합니다.
- 손쉬운 사용과 화면 녹화 권한을 다시 확인합니다.

### 캡처가 중간에 멈춤

- 캡처 중 마우스와 키보드를 사용하지 않습니다.
- 밀리의서재 창을 최소화하거나 다른 Space로 옮기지 않습니다.
- 실행 기록에서 마지막 오류를 확인합니다.

```text
~/Library/Logs/MillieOCRShortcut.log
```

### OCR 엔진 설치 실패

```bash
brew install python poppler llama.cpp
./install_surya_macos.sh --python "$(command -v python3)"
```

첫 OCR 실행은 Surya 모델을 내려받기 때문에 오래 걸릴 수 있습니다.

## 제거

```bash
launchctl bootout "gui/$(id -u)/com.millieocr.dashboard" 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.millieocr.dashboard.plist
rm -rf "$HOME/Library/Application Support/MillieOCR"
```

OCR 모델 캐시와 결과물은 자동 삭제하지 않습니다. 필요하면 다음 위치를 직접 확인한 뒤 제거하세요.

```text
~/.cache/codex-korean-ocr/surya2/
~/Documents/Codex/OCR Results/
```

## 라이선스와 외부 구성요소

이 저장소의 코드는 [MIT License](LICENSE)로 배포합니다.

- [Surya](https://github.com/datalab-to/surya) 코드는 Apache-2.0입니다.
- Surya 모델 가중치는 별도의 수정 OpenRAIL-M 조건이 적용됩니다. 개인·연구·일정 규모 이하 스타트업 사용과 상업적 사용 조건은 Surya 저장소의 최신 안내를 직접 확인하세요.
- [Orca](https://github.com/stablyai/orca)는 별도 프로젝트이며 이 저장소에 포함되지 않습니다.
- 밀리의서재는 해당 권리자의 상표입니다. 이 프로젝트는 밀리의서재와 제휴하거나 공식 승인받은 프로젝트가 아닙니다.

## 개발 검증

```bash
python3 -m py_compile *.py
zsh -n run_millie_ocr.sh install_local.sh
```

실제 책 전체를 다시 캡처하지 않고 형식 변환만 시험하려면 기존 `validation/extracted.txt`에 `text_to_markdown.py`와 `text_to_epub.py`를 실행할 수 있습니다.
