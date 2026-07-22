property runnerPath : (POSIX path of (path to home folder)) & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
property logPath : (POSIX path of (path to home folder)) & "Library/Logs/MillieOCRShortcut.log"

on run
	set launchCommand to "/bin/mkdir -p " & quoted form of ((POSIX path of (path to home folder)) & "Library/Logs") & " && " & ¬
		"/usr/bin/nohup /bin/zsh " & quoted form of runnerPath & " --auto >> " & ¬
		quoted form of logPath & " 2>&1 </dev/null &"
	do shell script launchCommand
	display notification "고속 캡처와 OCR을 시작했습니다." with title "밀리 OCR"
	return "밀리 OCR 작업을 시작했습니다."
end run
