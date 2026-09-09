Set fso = CreateObject("Scripting.FileSystemObject")
strScriptFolder = fso.GetParentFolderName(WScript.ScriptFullName)
strBridgeDir = fso.GetParentFolderName(strScriptFolder)
strPyw = "C:\Users\SERVER SMK AL-HUDA\AppData\Local\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(strPyw) Then
    strPyw = "C:\Python314\pythonw.exe"
End If
If Not fso.FileExists(strPyw) Then
    strPyw = "pythonw.exe"
End If

Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where (CommandLine Like '%bridge_telegram.py%' Or CommandLine Like '%allzxy_bot.py%') And (Name = 'pythonw.exe' Or Name = 'python.exe')")

If colProcesses.Count = 0 Then
    Set objProcess = objWMIService.Get("Win32_Process")
    strCommand = """" & strPyw & """ """ & strBridgeDir & "\bridge_telegram.py"""
    objProcess.Create strCommand, strBridgeDir, Null, intProcessID
End If
