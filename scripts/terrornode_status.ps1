Write-Host "=== TERRORNODE HEALTH CHECK ===" -ForegroundColor Cyan

Write-Host "`n--- RUNNING SERVICES ---"
$running = (Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and $_.Status -eq 'Running'}).Count
Write-Host "  Auto-start services running: $running"

Write-Host "`n--- MEMORY ---"
$os = Get-CimInstance Win32_OperatingSystem
$freeGB = [math]::Round($os.FreePhysicalMemory/1MB, 1)
$totalGB = [math]::Round($os.TotalVisibleMemorySize/1MB, 1)
$usedGB = [math]::Round($totalGB - $freeGB, 1)
Write-Host "  Total: $totalGB GB"
Write-Host "  Used:  $usedGB GB"
Write-Host "  Free:  $freeGB GB"

Write-Host "`n--- DISK ---"
$disk = Get-PSDrive C
$freeD = [math]::Round($disk.Free/1GB, 1)
$usedD = [math]::Round($disk.Used/1GB, 1)
Write-Host "  Total: $([math]::Round(($disk.Free + $disk.Used)/1GB, 1)) GB"
Write-Host "  Used:  $usedD GB"
Write-Host "  Free:  $freeD GB"

Write-Host "`n--- STARTUP PROGRAMS ---"
$startup = Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue
if ($startup) {
    Write-Host "  Count: $($startup.Count)"
    foreach ($s in $startup) {
        Write-Host "    - $($s.Name)"
    }
} else {
    Write-Host "  Count: 0"
}

Write-Host "`n--- UPTIME ---"
$boot = $os.LastBootUpTime
$uptime = (Get-Date) - $boot
Write-Host "  Last boot: $boot"
Write-Host "  Uptime: $($uptime.Hours)h $($uptime.Minutes)m"

Write-Host "`n--- TOP CPU PROCESSES ---"
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, @{N='CPU(s)';E={[math]::Round($_.CPU,1)}}, @{N='MemMB';E={[math]::Round($_.WorkingSet64/1MB,0)}} | Format-Table -AutoSize

Write-Host "=== DONE ===" -ForegroundColor Cyan
