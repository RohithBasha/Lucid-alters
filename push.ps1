git add .
git reset HEAD gen_chart.py
git reset HEAD run_chart.ps1
git commit -m "Add BB chart images to Telegram alerts"
git push
del gen_chart.py
del run_chart.ps1
