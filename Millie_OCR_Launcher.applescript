use framework "Foundation"
use scripting additions

property workflowPath : (POSIX path of (path to home folder)) & "Library/Application Support/MillieOCR/Millie_OCR.scpt"

on run
	try
		set workflowScript to load script POSIX file workflowPath
		return run workflowScript
	on error errorMessage number errorNumber
		display dialog "밀리 OCR 실행 파일을 불러오지 못했습니다." & return & return & errorMessage with title "밀리 OCR" buttons {"확인"} default button "확인" with icon caution
		return "밀리 OCR 실행 오류 " & errorNumber
	end try
end run
