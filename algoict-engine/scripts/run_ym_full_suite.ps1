# run_ym_full_suite.ps1
# =======================
# Launches V8 SB backtests on YM for 6 remaining years (2019-2023, 2025)
# IN PARALLEL. Each subprocess writes its own JSON + logs under analysis/.
#
# Usage: after YM 2024 validates, run:
#   powershell -ExecutionPolicy Bypass -File scripts/run_ym_full_suite.ps1

Set-Location 'C:\AI Projects\AlgoICT\algoict-engine'

$years = @(2019, 2020, 2021, 2022, 2023, 2025)

foreach ($y in $years) {
    $start = "$y-01-01"
    $end   = "$y-12-31"
    $json  = "analysis/sb_v8_ym_$y.json"
    $log   = "analysis/sb_v8_ym_$y.log"
    $err   = "analysis/sb_v8_ym_${y}_err.log"
    Write-Host "Launching YM $y backtest..."
    Start-Process -FilePath 'C:\Python314\python.exe' `
        -ArgumentList `
            '-u','scripts/run_backtest.py',
            '--strategy','silver_bullet',
            '--databento','../data/ym_1minute.csv',
            '--symbol-prefix','YM',
            '--symbol','YM',
            '--start',$start,
            '--end',$end,
            '--trade-management','trailing',
            '--kill-zones','london,ny_am,ny_pm',
            '--topstep','--combine-reset-on-breach',
            '--no-supabase',
            '--export-json',$json `
        -NoNewWindow -PassThru `
        -RedirectStandardOutput $log `
        -RedirectStandardError $err `
        | Select-Object Id, StartTime
}

Write-Host "All 6 YM backtests launched. Monitor via analysis/sb_v8_ym_YYYY.json"
