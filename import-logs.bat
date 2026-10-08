@echo off
rem Double-click on the PC that hosted the inhouse. Copies new ScrimTime logs
rem from Documents\Overwatch\Workshop into logs\, adds new players to
rem config\players.csv, and pushes everything so the website rebuilds.
rem One-time setup: install Python and Git, then run: pip install -r requirements.txt
cd /d "%~dp0"
python -m overtime import --add
if errorlevel 1 goto :done
git add logs config/players.csv
git diff --cached --quiet && (echo Nothing new to upload.& goto :done)
git commit -m "Add inhouse logs"
git push
:done
pause
