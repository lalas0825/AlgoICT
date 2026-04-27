' run_monitor_silent.vbs
' =====================
' VBScript wrapper that launches PowerShell COMPLETELY HIDDEN.
' Standard Windows trick: WindowStyle=0 in WSHShell.Run hides the
' powershell.exe window completely (no flash), unlike Task Scheduler's
' direct -WindowStyle Hidden flag which flashes for ~100ms during launch.
'
' Used by install_monitor.ps1 to launch monitor.ps1 every 60s without
' flickering a black PowerShell window on screen.

Dim shell, scriptPath, command
Set shell = CreateObject("WScript.Shell")
scriptPath = "C:\AI Projects\AlgoICT\algoict-engine\scripts\monitor.ps1"
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """"

' Run(command, windowStyle, waitOnReturn)
'   windowStyle 0  = hidden (no flash, true silent)
'   waitOnReturn   = False (fire and forget)
shell.Run command, 0, False
