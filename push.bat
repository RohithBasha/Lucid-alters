@echo off
cd /d "C:\Users\rohit\OneDrive\Desktop\commodity-bb-alerts"
git add chart_generator.py telegram_notifier.py main.py requirements.txt .github/workflows/check_bands.yml bot_commands.py
git commit -m "Add BB chart images to Telegram alerts"
git push
del gen_chart.py 2>nul
del run_chart.ps1 2>nul
del push.ps1 2>nul
del "%~f0"
