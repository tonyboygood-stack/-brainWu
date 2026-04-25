# Vault 自動同步腳本
# 每天凌晨 6:00 執行，將異動推送到 GitHub

$repoPath = "C:\Users\user\Documents\GitHub\-"
$logFile = "$repoPath\000_Agent\sync-log.txt"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Set-Location $repoPath

try {
    $status = git status --porcelain
    if ($status) {
        git add -A
        git commit -m "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
        $pushResult = git push origin main 2>&1
        Add-Content $logFile "[$timestamp] 同步成功: $pushResult"
    } else {
        Add-Content $logFile "[$timestamp] 無異動，略過"
    }
} catch {
    Add-Content $logFile "[$timestamp] 同步失敗: $_"
}
