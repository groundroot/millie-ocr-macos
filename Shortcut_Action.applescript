on run {input, parameters}
	set homePath to POSIX path of (path to home folder)
	set runnerPath to homePath & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
	set logDirectory to homePath & "Library/Logs"
	set logPath to logDirectory & "/MillieOCRShortcut.log"
	set launchCommand to "/bin/mkdir -p " & quoted form of logDirectory & " && " & ¬
		"/usr/bin/nohup /bin/zsh " & quoted form of runnerPath & " --auto >> " & ¬
		quoted form of logPath & " 2>&1 </dev/null &"
	do shell script launchCommand
	display notification "고속 캡처와 OCR을 시작했습니다." with title "밀리 OCR"
	return input
end run
