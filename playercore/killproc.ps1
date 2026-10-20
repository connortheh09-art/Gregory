param([string]$Match)
$p = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
     Where-Object { $_.CommandLine -like "*$Match*" }
foreach ($x in $p) {
  Write-Output ("KILL " + $x.ProcessId)
  Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue
}
