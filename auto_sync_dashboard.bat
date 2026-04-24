@echo off
setlocal enabledelayedexpansion
REM =====================================================================
REM Daily auto-sync — runs the full Noah dashboard pipeline end-to-end.
REM 1) Pull IG metrics from Instagram
REM 2) Push metrics into Notion (shortcode match -> planning row promote -> orphan)
REM 3) Transcribe newly-Posted reels (skips already-transcribed)
REM 4) Pull Pillar values from Notion back into metrics.json
REM 5) Commit + push metrics.json to GitHub so Streamlit Cloud rebuilds
REM 6) Append one status line to the vault sync-log for audit trail
REM
REM Scheduled by Windows Task Scheduler: task "Noah Dashboard Sync", 7pm daily.
REM Verbose log: auto_sync.log (overwritten each run).
REM Audit log:   ..\..\01 Daily Logs\C Logs\[C] sync-log.md (append-only).
REM =====================================================================

cd /d "%~dp0"

set LOG=auto_sync.log
set SYNC_LOG=C:\Users\vaymx\Vaults\Second Brain\01 Daily Logs\C Logs\[C] sync-log.md
set STATUS=OK
set FAIL_STEP=

echo === %date% %time% === > %LOG%

echo [1/5] Pulling IG metrics... >> %LOG%
python sync_ig_metrics.py >> %LOG% 2>&1
if errorlevel 1 if "!STATUS!"=="OK" ( set STATUS=FAIL & set FAIL_STEP=IG sync )

echo. >> %LOG%
echo [2/5] Pushing to Notion... >> %LOG%
python push_to_notion.py >> %LOG% 2>&1
if errorlevel 1 if "!STATUS!"=="OK" ( set STATUS=FAIL & set FAIL_STEP=Notion push )

echo. >> %LOG%
echo [3/5] Transcribing newly-posted reels... >> %LOG%
python transcribe_posted_reels.py >> %LOG% 2>&1
if errorlevel 1 (
    echo [WARN] transcribe step exited non-zero: check IG cookies. >> %LOG%
    if "!STATUS!"=="OK" ( set STATUS=FAIL & set FAIL_STEP=transcribe )
)

echo. >> %LOG%
echo [4/5] Pulling Pillars from Notion... >> %LOG%
python sync_pillars_from_notion.py >> %LOG% 2>&1
if errorlevel 1 if "!STATUS!"=="OK" ( set STATUS=FAIL & set FAIL_STEP=pillar sync )

echo. >> %LOG%
echo [5/5] Committing and pushing metrics.json to GitHub... >> %LOG%
git add metrics.json >> %LOG% 2>&1
git diff --cached --quiet metrics.json
if errorlevel 1 (
    git commit -m "Auto-sync metrics.json [%date% %time%]" >> %LOG% 2>&1
    git push origin main >> %LOG% 2>&1
    if errorlevel 1 if "!STATUS!"=="OK" ( set STATUS=FAIL & set FAIL_STEP=git push )
    echo metrics.json updated and pushed. >> %LOG%
) else (
    echo metrics.json unchanged: skipping commit. >> %LOG%
)

echo. >> %LOG%
echo [6/6] Appending audit line to sync-log.md... >> %LOG%
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')"`) do set UTC=%%t

if "!STATUS!"=="OK" (
    echo [!UTC! UTC] OK: sync done, Notion updated, transcripts processed>>"%SYNC_LOG%"
) else (
    echo [!UTC! UTC] FAILED at !FAIL_STEP!: see auto_sync.log>>"%SYNC_LOG%"
)

echo. >> %LOG%
echo === DONE %date% %time% === >> %LOG%

endlocal
