# run_nq_v9_suite.ps1
# ====================
# Launch V9 (session recency) NQ backtests for 2019-2023 in parallel.
# 2024 and 2025 already done separately.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run_nq_v9_suite.ps1

Set-Location 'C:\AI Projects\AlgoICT\algoict-engine'

$years = @(2019, 2020, 2021, 2022, 2023)

foreach ($y in $years) {
    $start = "$y-01-01"
    $end   = "$y-12-31"
    $json  = "analysis/sb_v9_session_recency_$y.json"
    $log   = "analysis/sb_v9_session_recency_$y.log"
    $err   = "analysis/sb_v9_session_recency_${y}_err.log"
    Write-Host "Launching NQ V9 $y backtest..."
    Start-Process -FilePath 'C:\Python314\python.exe' `
        -ArgumentList `
            '-u','scripts/run_backtest.py',
            '--strategy','silver_bullet',
            '--databento','../data/nq_1minute.csv',
            '--symbol-prefix','NQ',
            '--symbol','MNQ',
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

Write-Host "All 5 NQ V9 backtests launched (2019-2023)."
