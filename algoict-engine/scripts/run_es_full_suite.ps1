# run_es_full_suite.ps1
# =======================
# Launches V8 SB backtests on ES for 6 remaining years (2019-2023, 2025)
# IN PARALLEL. Each subprocess writes its own JSON + logs under analysis/.
#
# Usage: after ES 2024 validates, run:
#   powershell -ExecutionPolicy Bypass -File scripts/run_es_full_suite.ps1
#
# Machine should handle 3-6 parallel (each uses ~500MB to load ES CSV,
# ~200-300MB active). Sequencing not required if RAM > 8GB.

Set-Location 'C:\AI Projects\AlgoICT\algoict-engine'

$years = @(2019, 2020, 2021, 2022, 2023, 2025)

foreach ($y in $years) {
    $start = "$y-01-01"
    $end   = "$y-12-31"
    $json  = "analysis/sb_v8_es_$y.json"
    $log   = "analysis/sb_v8_es_$y.log"
    $err   = "analysis/sb_v8_es_${y}_err.log"
    Write-Host "Launching ES $y backtest..."
    Start-Process -FilePath 'C:\Python314\python.exe' `
        -ArgumentList `
            '-u','scripts/run_backtest.py',
            '--strategy','silver_bullet',
            '--databento','../data/es_1minute.csv',
            '--symbol-prefix','ES',
            '--symbol','ES',
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

Write-Host "All 6 ES backtests launched. Monitor via analysis/sb_v8_es_YYYY.json"
