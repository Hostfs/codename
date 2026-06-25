Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "        Memory Hog Process Started!       " -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

$hog = New-Object System.Collections.ArrayList
Write-Host "Allocating memory via PowerShell..."

for ($i = 1; $i -le 1500; $i++) {
    $arr = New-Object byte[] 1048576
    $hog.Add($arr) | Out-Null
    if ($i % 100 -eq 0) {
        Write-Host "Allocated $($i) MB..."
    }
}

Write-Host ""
Write-Host "✅ Memory allocation complete (approx 1.5GB)." -ForegroundColor Green
Write-Host "▶️ PowerShell PID: $PID" -ForegroundColor Red
Write-Host "Holding memory. Check your Resource Advisor app now!" -ForegroundColor Yellow
Write-Host "(Press Ctrl+C to stop manually)"

while ($true) {
    Start-Sleep -Seconds 10
}
