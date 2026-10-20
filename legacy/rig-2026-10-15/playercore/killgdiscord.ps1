$ErrorActionPreference = "SilentlyContinue"
$found = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'gdiscord' } | ForEach-Object {
  Write-Output ("KILL " + $_.ProcessId)
  Stop-Process -Id $_.ProcessId -Force
  $found++
}
Write-Output ("DONE killed=" + $found)
