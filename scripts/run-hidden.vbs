Option Explicit

Dim shell, scriptPath, command, exitCode

If WScript.Arguments.Count <> 1 Then
    WScript.Quit 2
End If

scriptPath = WScript.Arguments(0)
Set shell = CreateObject("WScript.Shell")

command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & _
    Chr(34) & scriptPath & Chr(34)

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
