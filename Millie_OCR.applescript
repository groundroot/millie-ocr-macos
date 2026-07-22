property runnerPath : (POSIX path of (path to home folder)) & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
property logPath : (POSIX path of (path to home folder)) & "Library/Logs/MillieOCRShortcut.log"

on run
	try
		set selectedFolder to choose folder with prompt "PDF·Markdown·EPUB 결과를 저장할 폴더를 선택하세요."
	on error number -128
		return "사용자가 저장 위치 선택을 취소했습니다."
	end try
	set resultRoot to POSIX path of selectedFolder
	set launchCommand to "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Library/Logs") & " && " & ¬
		"/bin/zsh " & quoted form of runnerPath & " --auto run " & quoted form of resultRoot & " >> " & ¬
		quoted form of logPath & " 2>&1"
	display notification "선택한 폴더에 고속 캡처와 OCR을 시작했습니다." with title "밀리 OCR"
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
