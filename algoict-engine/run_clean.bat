@echo off
REM Run the AlgoICT engine with a cleaned-up stdout stream.
REM Full verbose log still goes to engine.log.

python -m main --mode paper 2>&1 | findstr /R "BAR EVAL SIGNAL SWEEP SignalR Warm-up tracked_levels SWC mood= ERROR CRITICAL FLATTEN bot_state Telegram"
