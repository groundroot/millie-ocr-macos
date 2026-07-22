on run {input, parameters}
	set homePath to POSIX path of (path to home folder)
	set runnerPath to homePath & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
	set logDirectory to homePath & "Library/Logs"
	set logPath to logDirectory & "/MillieOCRShortcut.log"
	try
		set selectedFolder to choose folder with prompt "밀리 OCR 결과를 저장할 폴더를 선택하세요."
	on error number -128
		return input
	end try
	set outputChoices to {"스캔만 — PNG 이미지", "PDF만 — OCR 없는 이미지 PDF", "OCR PDF만 — 검색 가능한 PDF", "Markdown만 — OCR 본문", "모두 만들기 — OCR PDF + Markdown + EPUB"}
	try
		set selectedMode to choose from list outputChoices with title "밀리 OCR · 결과 선택" with prompt "캡처가 끝난 뒤 만들 결과를 선택하세요." default items {item 5 of outputChoices} OK button name "계속" cancel button name "취소"
	on error number -128
		return input
	end try
	if selectedMode is false then return input
	set selectedText to item 1 of selectedMode
	if selectedText starts with "스캔만" then
		set outputMode to "scan-only"
		set outputLabel to "스캔 이미지"
	else if selectedText starts with "PDF만" then
		set outputMode to "pdf-only"
		set outputLabel to "OCR 없는 PDF"
	else if selectedText starts with "OCR PDF만" then
		set outputMode to "ocr-pdf"
		set outputLabel to "검색 가능한 OCR PDF"
	else if selectedText starts with "Markdown만" then
		set outputMode to "md-only"
		set outputLabel to "Markdown"
	else
		set outputMode to "all"
		set outputLabel to "OCR PDF·Markdown·EPUB"
	end if
	set resultRoot to POSIX path of selectedFolder
	set launchCommand to "/bin/mkdir -p " & quoted form of logDirectory & " && " & ¬
		"/bin/zsh " & quoted form of runnerPath & " --auto run " & quoted form of resultRoot & " " & quoted form of outputMode & " >> " & ¬
		quoted form of logPath & " 2>&1"
	display notification (outputLabel & " 작업을 시작했습니다.") with title "밀리 OCR"
	-- Let the result chooser close before the long-running shell task starts.
	delay 0.1
	try
		tell application id "kr.co.millie.MillieShelf" to activate
	end try
	try
		with timeout of 604800 seconds
			do shell script launchCommand
		end timeout
	on error errorMessage number errorNumber
		display notification "작업이 중단됐습니다. 대시보드에서 원인을 확인해 주세요." with title "밀리 OCR"
	end try
	return input
end run
