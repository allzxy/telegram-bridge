Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where (CommandLine Like '%bridge_telegram.py%' Or CommandLine Like '%allzxy_bot.py%') And (Name = 'pythonw.exe' Or Name = 'python.exe')")

If colProcesses.Count = 0 Then
    Set objProcess = objWMIService.Get("Win32_Process")
    strCommand = """C:\Users\SERVER SMK AL-HUDA\AppData\Local\Programs\Python\Python312\pythonw.exe"" ""E:\Alfan\telegram-bridge\bridge_telegram.py"""
    objProcess.Create strCommand, "E:\Alfan\telegram-bridge", Null, intProcessID
End If
