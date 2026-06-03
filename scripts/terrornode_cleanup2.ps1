# TerrorNode Cleanup Part 2 - Remove remaining bloat
Write-Host "=== TERRORNODE CLEANUP PART 2 ===" -ForegroundColor Cyan

# Disable remaining startup items
Write-Host "`n--- DISABLING STARTUP ---" -ForegroundColor Yellow
$regPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run"
)

$killList = @("OneDrive", "Steam", "VideoGuard", "Proton", "MicrosoftEdgeAutoLaunch", "Nahimic", "NVIDIA")

foreach ($path in $regPaths) {
    $items = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue
    if ($items) {
        foreach ($prop in $items.PSObject.Properties) {
            if ($prop.Name -eq "PSPath" -or $prop.Name -eq "PSParentPath" -or $prop.Name -eq "PSChildName" -or $prop.Name -eq "PSProvider" -or $prop.Name -eq "PSDrive") { continue }
            foreach ($pattern in $killList) {
                if ($prop.Name -like "*$pattern*" -or $prop.Value -like "*$pattern*") {
                    Write-Host "  Removing: $($prop.Name)" -ForegroundColor Red
                    Remove-ItemProperty -Path $path -Name $prop.Name -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

# Disable Nahimic service
Write-Host "`n--- DISABLING NAHIMIC ---" -ForegroundColor Yellow
$nahimic = Get-Service -Name "NahimicService" -ErrorAction SilentlyContinue
if ($nahimic) {
    Stop-Service -Name "NahimicService" -Force -ErrorAction SilentlyContinue
    Set-Service -Name "NahimicService" -StartupType Disabled -ErrorAction SilentlyContinue
    Write-Host "  Disabled NahimicService"
}

# Disable NVIDIA telemetry/share (keep driver, kill extras)
Write-Host "`n--- DISABLING NVIDIA EXTRAS ---" -ForegroundColor Yellow
$nvServices = @("NvTelemetryContainer", "NVDisplay.ContainerLocalSystem")
foreach ($svc in $nvServices) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        # Don't disable display container - just telemetry
        if ($svc -like "*Telemetry*") {
            Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
            Set-Service -Name $svc -StartupType Disabled -ErrorAction SilentlyContinue
            Write-Host "  Disabled: $svc"
        }
    }
}

# Kill NVIDIA Share process
Stop-Process -Name "NVIDIA Share" -Force -ErrorAction SilentlyContinue
Write-Host "  Killed NVIDIA Share process"

# Reduce Defender CPU impact (exclude Python and model files)
Write-Host "`n--- CONFIGURING DEFENDER ---" -ForegroundColor Yellow
Add-MpPreference -ExclusionPath "C:\Python38" -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionPath "C:\Users\jwebb\swarm" -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionExtension ".pt" -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionExtension ".onnx" -ErrorAction SilentlyContinue
Write-Host "  Added exclusions for Python, swarm dir, and model files"

# Create swarm working directory
Write-Host "`n--- CREATING SWARM DIRECTORY ---" -ForegroundColor Yellow
New-Item -ItemType Directory -Path "C:\Users\jwebb\swarm" -Force | Out-Null
New-Item -ItemType Directory -Path "C:\Users\jwebb\swarm\models" -Force | Out-Null
New-Item -ItemType Directory -Path "C:\Users\jwebb\swarm\patterns" -Force | Out-Null
New-Item -ItemType Directory -Path "C:\Users\jwebb\swarm\checkpoints" -Force | Out-Null
Write-Host "  Created C:\Users\jwebb\swarm\"

# Final status
Write-Host "`n--- FINAL STATUS ---" -ForegroundColor Cyan
$running = (Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and $_.Status -eq 'Running'}).Count
$os = Get-CimInstance Win32_OperatingSystem
$freeRAM = [math]::Round($os.FreePhysicalMemory/1MB, 1)
Write-Host "  Running services: $running"
Write-Host "  Free RAM: $freeRAM GB"
Write-Host "  Swarm dir: C:\Users\jwebb\swarm\"
Write-Host "`n=== CLEANUP COMPLETE ===" -ForegroundColor Cyan
