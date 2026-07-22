on cleanText(rawValue)
	try
		if rawValue is missing value then return ""
		set cleaned to rawValue as text
		set AppleScript's text item delimiters to {return, linefeed, tab}
		set pieces to text items of cleaned
		set AppleScript's text item delimiters to " "
		set cleaned to pieces as text
		set AppleScript's text item delimiters to ""
		return cleaned
	on error
		set AppleScript's text item delimiters to ""
		return ""
	end try
end cleanText

on describeElement(elementRef)
	set roleText to ""
	set nameText to ""
	set descriptionText to ""
	set valueText to ""
	try
		set roleText to my cleanText(role of elementRef)
	end try
	if roleText is not in {"AXStaticText", "AXSlider", "AXHeading", "AXButton", "AXWebArea"} then return ""
	try
		set nameText to my cleanText(name of elementRef)
	end try
	try
		set descriptionText to my cleanText(description of elementRef)
	end try
	try
		set valueText to my cleanText(value of elementRef)
	end try
	if roleText is "" and nameText is "" and descriptionText is "" and valueText is "" then return ""
	return "role=" & roleText & " name=" & nameText & " description=" & descriptionText & " value=" & valueText
end describeElement

on snapshotProcess(processRef)
	tell application "System Events"
		if (count of windows of processRef) is 0 then error "밀리의서재에서 열린 책 창을 찾지 못했습니다."
		set processID to unix id of processRef
		set frontWindow to front window of processRef
		set windowTitle to my cleanText(name of frontWindow)
		set outputLines to {processID as text, windowTitle}
		set allElements to entire contents of frontWindow
		repeat with elementRef in allElements
			set elementLine to my describeElement(elementRef)
			if elementLine is not "" then set end of outputLines to elementLine
		end repeat
		set AppleScript's text item delimiters to linefeed
		set outputText to outputLines as text
		set AppleScript's text item delimiters to ""
		return outputText
	end tell
end snapshotProcess

on closeVisibleMenu(processRef)
	tell application "System Events"
		set allElements to entire contents of front window of processRef
		repeat with elementRef in allElements
			set roleText to ""
			set nameText to ""
			set descriptionText to ""
			try
				set roleText to role of elementRef as text
			end try
			try
				set nameText to name of elementRef as text
			end try
			try
				set descriptionText to description of elementRef as text
			end try
			if roleText is "AXButton" and (nameText contains "닫기" or descriptionText contains "닫기") then
				try
					perform action "AXPress" of elementRef
				on error
					click elementRef
				end try
				delay 0.05
				return true
			end if
		end repeat
	end tell
	return false
end closeVisibleMenu

on run argv
	if (count of argv) < 2 then error "사용법: millie_native.applescript ACTION BUNDLE_ID [KEY_CODE]"
	set actionName to item 1 of argv
	set bundleID to item 2 of argv
	tell application "System Events"
		set matchingProcesses to application processes whose bundle identifier is bundleID
		if (count of matchingProcesses) is 0 then error "밀리의서재 앱이 실행 중이 아닙니다."
		set processRef to item 1 of matchingProcesses
		if actionName is "focus" or actionName is "press" or actionName is "close" then
			set frontmost of processRef to true
			delay 0.04
		end if
		if actionName is "press" then
			if (count of argv) < 3 then error "키 코드가 필요합니다."
			set requestedKeyCode to item 3 of argv as integer
			key code requestedKeyCode
			delay 0.015
		else if actionName is "close" then
			my closeVisibleMenu(processRef)
		end if
		return my snapshotProcess(processRef)
	end tell
end run
