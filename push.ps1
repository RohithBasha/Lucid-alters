git add .
git commit -m "Harden code: 5min cron, retries, PRIORITY signals"
git push
Remove-Item $MyInvocation.MyCommand.Path
