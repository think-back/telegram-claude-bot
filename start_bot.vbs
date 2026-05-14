Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\workspace\telegram-claude-bot"
WshShell.Run "pythonw bot.py", 0, False
