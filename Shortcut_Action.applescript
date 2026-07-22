on run {input, parameters}
	set homePath to POSIX path of (path to home folder)
	set runnerPath to homePath & "Library/Application Support/MillieOCR/run_millie_ocr.sh"
	set logDirectory to homePath & "Library/Logs"
	set logPath to logDirectory & "/MillieOCRShortcut.log"
	try
		set selectedFolder to choose folder with prompt "PDF·Markdown·EPUB 결과를 저장할 폴더를 선택하세요."
	on error number -128
		return input
	end try
	set resultRoot to POSIX path of selectedFolder
	set launchCommand to "/bin/mkdir -p " & quoted form of logDirectory & " && " & ¬
		"/usr/bin/nohup /bin/zsh " & quoted form of runnerPath & " --auto run " & quoted form of resultRoot & " >> " & ¬
		quoted form of logPath & " 2>&1 </dev/null &"
	do shell script launchCommand
	display notification "선택한 폴더에 고속 캡처와 OCR을 시작했습니다." with title "밀리 OCR"
	return input
end run
