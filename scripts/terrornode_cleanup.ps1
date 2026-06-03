# TerrorNode Cleanup & Setup Script
# Run as: powershell -ExecutionPolicy Bypass -File terrornode_cleanup.ps1

Write-Host "=== TERRORNODE SETUP ===" -ForegroundColor Cyan
Write-Host ""

# 1. Remove bloatware
Write-Host "--- REMOVING BLOATWARE ---" -ForegroundColor Yellow
$bloat = @(
    "*BingWeather*", "*BingNews*", "*BingFinance*", "*BingSports*",
    "*Xbox*", "*Zune*", "*Skype*", "*OneNote*", "*Office.OneNote*",
    "*MicrosoftSolitaire*", "*Candy*", "*BubbleWitch*", "*Facebook*",
    "*Twitter*", "*Flipboard*", "*Royal*", "*Sway*", "*Speed*",
    "*Dolby*", "*MSN*", "*Getstarted*", "*3DViewer*", "*3DBuilder*",
    "*MixedReality*", "*Print3D*", "*Feedback*", "*Microsoft.People*",
    "*WindowsMaps*", "*Messaging*", "*Wallet*", "*ConnectivityStore*",
    "*Microsoft.Todos*", "*PowerAutomate*", "*Clipchamp*",
    "*Microsoft.549981C3F5F10*", "*Teams*", "*YourPhone*", "*Phone*",
    "*GetHelp*", "*Tips*", "*LinkedInForWindows*", "*Disney*",
    "*Spotify*", "*TikTok*", "*Instagram*", "*Netflix*",
    "*Advertising*", "*Paint3D*", "*ScreenSketch*"
)

$removed = 0
foreach ($app in $bloat) {
    $packages = Get-AppxPackage -Name $app -ErrorAction SilentlyContinue
    foreach ($pkg in $packages) {
        Write-Host "  Removing: $($pkg.Name)" -ForegroundColor Red
        Remove-AppxPackage -Package $pkg.PackageFullName -ErrorAction SilentlyContinue
        $removed++
    }
}
Write-Host "  Removed $removed bloatware apps" -ForegroundColor Green

# 2. Disable startup bloat
Write-Host ""
Write-Host "--- DISABLING STARTUP ITEMS ---" -ForegroundColor Yellow
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$items = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
if ($items) {
    $startupPatterns = @("OneDrive", "Cortana", "Teams", "Spotify", "Discord", "MSI", "Nahimic", "Dragon", "SteelSeries")
    foreach ($prop in $items.PSObject.Properties) {
        if ($prop.Name -eq "PSPath" -or $prop.Name -eq "PSParentPath" -or $prop.Name -eq "PSChildName" -or $prop.Name -eq "PSProvider" -or $prop.Name -eq "PSDrive") { continue }
        foreach ($pattern in $startupPatterns) {
            if ($prop.Name -like "*$pattern*" -or $prop.Value -like "*$pattern*") {
                Write-Host "  Disabling startup: $($prop.Name)" -ForegroundColor Red
                Remove-ItemProperty -Path $regPath -Name $prop.Name -ErrorAction SilentlyContinue
            }
        }
    }
}

# 3. Disable services that kill HDD performance
Write-Host ""
Write-Host "--- DISABLING SLOW SERVICES ---" -ForegroundColor Yellow
$servicesToDisable = @(
    "DiagTrack",
    "dmwappushservice",
    "SysMain",
    "WSearch",
    "XblAuthManager",
    "XblGameSave",
    "XboxNetApiSvc",
    "XboxGipSvc",
    "WMPNetworkSvc"
)

foreach ($svc in $servicesToDisable) {
    $service = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "  Disabling: $svc ($($service.DisplayName))" -ForegroundColor Red
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        Set-Service -Name $svc -StartupType Disabled -ErrorAction SilentlyContinue
    }
}

# 4. Performance tweaks
Write-Host ""
Write-Host "--- PERFORMANCE TWEAKS ---" -ForegroundColor Yellow

# Visual effects to performance mode
$regPerf = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
New-Item -Path $regPerf -Force -ErrorAction SilentlyContinue | Out-Null
Set-ItemProperty -Path $regPerf -Name "VisualFXSetting" -Value 2 -ErrorAction SilentlyContinue
Write-Host "  Visual effects: Best Performance"

# Disable transparency
Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" -Name "EnableTransparency" -Value 0 -ErrorAction SilentlyContinue
Write-Host "  Transparency: Disabled"

# High performance power plan
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c 2>$null
Write-Host "  Power plan: High Performance"

# Disable hibernation (frees disk space)
powercfg /hibernate off 2>$null
Write-Host "  Hibernation: Disabled (saves disk space)"

# 5. System status
Write-Host ""
Write-Host "--- SYSTEM STATUS ---" -ForegroundColor Cyan
Write-Host "  OS: $((Get-CimInstance Win32_OperatingSystem).Caption)"
Write-Host "  CPU: $((Get-CimInstance Win32_Processor).Name)"
Write-Host "  RAM: $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB, 1)) GB"
Write-Host "  GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>$null)"
Write-Host "  Python: $(python --version 2>&1)"
Write-Host "  Disk Free: $([math]::Round((Get-PSDrive C).Free/1GB, 1)) GB free"

Write-Host ""
Write-Host "=== CLEANUP COMPLETE ===" -ForegroundColor Cyan
