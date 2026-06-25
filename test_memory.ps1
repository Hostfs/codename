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
Write-Host "🔥 Starting infinite CPU loop to trigger AI..." -ForegroundColor Red
Write-Host "▶️ PowerShell PID: $PID" -ForegroundColor Red
Write-Host "Holding memory and burning CPU. Check your Resource Advisor app now!" -ForegroundColor Yellow
Write-Host "(Press Ctrl+C to stop manually)"

# 무한 루프를 돌며 CPU 한 코어를 100% 가깝게 사용하게 만듭니다.
while ($true) {
    $math = [math]::Sin(1.2345)
}
