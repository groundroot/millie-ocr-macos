use framework "Foundation"
use framework "ApplicationServices"
use framework "CoreGraphics"
use scripting additions

property runnerPath : (POSIX path of (path to home folder)) & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
property logPath : (POSIX path of (path to home folder)) & "Library/Logs/MillieOCRShortcut.log"
property permissionMarkerPath : (POSIX path of (path to home folder)) & ".cache/millie-ocr/permission-setup.request"
property permissionResultPath : (POSIX path of (path to home folder)) & ".cache/millie-ocr/permission-setup.result"

on permissionMode()
	try
		return do shell script "/bin/cat " & quoted form of permissionMarkerPath
	on error
		return ""
	end try
end permissionMode

on writePermissionResult(resultText)
	set resultFile to POSIX file permissionResultPath
	set fileHandle to missing value
	try
		set fileHandle to open for access resultFile with write permission
		set eof fileHandle to 0
		write resultText to fileHandle
		close access fileHandle
	on error
		try
			if fileHandle is not missing value then close access fileHandle
		end try
	end try
end writePermissionResult

on openPrivacyPane(permissionKind)
	if permissionKind is "accessibility" then
		set settingsURL to "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
	else
		set settingsURL to "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
	end if
	do shell script "/usr/bin/open " & quoted form of settingsURL
end openPrivacyPane

on requestAccessibilityPermission()
	set promptOptions to current application's NSDictionary's dictionaryWithObject:true forKey:(current application's kAXTrustedCheckOptionPrompt)
	current application's AXIsProcessTrustedWithOptions(promptOptions)
	delay 0.4
	if (current application's AXIsProcessTrusted() as boolean) then
		my writePermissionResult("allowed")
		return
	end if
	my openPrivacyPane("accessibility")
	try
		display dialog "손쉬운 사용에서 반드시 ‘밀리 OCR’을 켜세요. ‘밀리의서재’가 아닙니다. 켠 다음 권한 확인을 누르세요." with title "1/2 · 손쉬운 사용 권한" buttons {"설치 중단", "권한 확인"} default button "권한 확인" cancel button "설치 중단" with icon caution
	on error number -128
		my writePermissionResult("cancelled")
		return
	end try
	if (current application's AXIsProcessTrusted() as boolean) then
		my writePermissionResult("allowed")
	else
		my writePermissionResult("retry")
	end if
end requestAccessibilityPermission

on requestScreenCapturePermission()
	if (current application's CGPreflightScreenCaptureAccess() as boolean) then
		my writePermissionResult("allowed")
		return
	end if
	current application's CGRequestScreenCaptureAccess()
	delay 0.4
	if (current application's CGPreflightScreenCaptureAccess() as boolean) then
		my writePermissionResult("allowed")
		return
	end if
	my openPrivacyPane("screen")
	try
		display dialog "화면 및 시스템 오디오 녹음에서 반드시 ‘밀리 OCR’을 켜세요. 오디오는 사용하지 않지만 책 화면 캡처에 화면 권한이 필요합니다. 켠 다음 권한 확인을 누르세요." with title "2/2 · 화면 녹화 권한" buttons {"설치 중단", "권한 확인"} default button "권한 확인" cancel button "설치 중단" with icon caution
	on error number -128
		my writePermissionResult("cancelled")
		return
	end try
	if (current application's CGPreflightScreenCaptureAccess() as boolean) then
		my writePermissionResult("allowed")
	else
		my writePermissionResult("retry")
	end if
end requestScreenCapturePermission

on runPermissionSetup(permissionKind)
	if permissionKind is "accessibility" then
		my requestAccessibilityPermission()
	else if permissionKind is "screen" then
		my requestScreenCapturePermission()
	else
		my writePermissionResult("invalid")
	end if
end runPermissionSetup

on chooseOutputMode()
	set outputChoices to {"스캔만 — PNG 이미지", "PDF만 — OCR 없는 이미지 PDF", "OCR PDF만 — 검색 가능한 PDF", "Markdown만 — OCR 본문", "모두 만들기 — OCR PDF + Markdown + EPUB"}
	set selectedMode to choose from list outputChoices with title "밀리 OCR · 결과 선택" with prompt "캡처가 끝난 뒤 만들 결과를 선택하세요." default items {item 5 of outputChoices} OK button name "계속" cancel button name "취소"
	if selectedMode is false then return missing value
	set selectedText to item 1 of selectedMode
	if selectedText starts with "스캔만" then return "scan-only"
	if selectedText starts with "PDF만" then return "pdf-only"
	if selectedText starts with "OCR PDF만" then return "ocr-pdf"
	if selectedText starts with "Markdown만" then return "md-only"
	return "all"
end chooseOutputMode

on outputModeLabel(modeCode)
	if modeCode is "scan-only" then return "스캔 이미지"
	if modeCode is "pdf-only" then return "OCR 없는 PDF"
	if modeCode is "ocr-pdf" then return "검색 가능한 OCR PDF"
	if modeCode is "md-only" then return "Markdown"
	return "OCR PDF·Markdown·EPUB"
end outputModeLabel

on run
	set requestedPermission to my permissionMode()
	if requestedPermission is not "" then
		my runPermissionSetup(requestedPermission)
		return "밀리 OCR 권한 확인을 마쳤습니다."
	end if
	try
		set selectedFolder to choose folder with prompt "밀리 OCR 결과를 저장할 폴더를 선택하세요."
	on error number -128
		return "사용자가 저장 위치 선택을 취소했습니다."
	end try
	try
		set outputMode to my chooseOutputMode()
	on error number -128
		return "사용자가 결과 선택을 취소했습니다."
	end try
	if outputMode is missing value then return "사용자가 결과 선택을 취소했습니다."
	set resultRoot to POSIX path of selectedFolder
	set launchCommand to "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Library/Logs") & " && " & ¬
		"/bin/zsh " & quoted form of runnerPath & " --auto run " & quoted form of resultRoot & " " & quoted form of outputMode & " >> " & ¬
		quoted form of logPath & " 2>&1"
	display notification ((my outputModeLabel(outputMode)) & " 작업을 시작했습니다.") with title "밀리 OCR"
	-- Give the native chooser one event-loop turn to close, then return focus to the reader.
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
		return "밀리 OCR 오류 " & errorNumber & ": " & errorMessage
	end try
	return "밀리 OCR 작업을 완료했습니다."
end run
