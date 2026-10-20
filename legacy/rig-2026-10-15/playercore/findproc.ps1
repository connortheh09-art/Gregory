param([string]$Match)
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -like "*$Match*" } |
  Select-Object -ExpandProperty ProcessId
