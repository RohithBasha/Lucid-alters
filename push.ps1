git add .
git commit -m "Add interactive /status command for live price and BB levels"
git push
Remove-Item $MyInvocation.MyCommand.Path
