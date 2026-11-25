# تثبيتُ إضافة «Bughya — بُغية» في Claude Desktop بنقرتين: يجد ملفَّ الإضافة بجانبه، وينتظر إغلاقَ Claude،
# ثمّ يفتحه والملفُّ معه، فيعرض Claude نافذةَ التثبيت. لا يغيّر شيئًا في الجهاز غيرَ ذلك.
Add-Type -AssemblyName PresentationFramework
$title = 'Bughya — بُغية'
function Say($text, $icon = 'Information', $buttons = 'OK') {
    if ($env:BUGHYA_DRYRUN) { Write-Host "[$icon] $text"; return 'OK' }
    return [System.Windows.MessageBox]::Show($text, $title, $buttons, $icon)
}
function Get-ClaudeApp {
    Get-Process -Name claude -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and ($_.Path -like '*\WindowsApps\Claude_*' -or $_.Path -like '*\AnthropicClaude\*') }
}

$dir  = Split-Path -Parent $PSCommandPath
$mcpb = Get-ChildItem -LiteralPath $dir -Filter '*.mcpb' | Select-Object -First 1
if (-not $mcpb) {
    Say "لم أجد ملفّ الإضافة (.mcpb) بجانب هذا الملفّ.`n`nفُكّ المجلّد المضغوط كلَّه، ثمّ انقر على هذا الملفّ من داخله." 'Error' | Out-Null
    exit 1
}
$launchers = @(
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\claude-desktop.exe'),   # Claude من متجر ويندوز
    (Join-Path $env:LOCALAPPDATA 'AnthropicClaude\claude.exe')                  # Claude من موقع Anthropic
)
$exe = $launchers | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $exe) {
    Say "لم أجد برنامج Claude لسطح المكتب على هذا الجهاز.`n`nنصّبه أوّلًا، وادخل فيه بحسابك، ثمّ أعد المحاولة." 'Error' | Out-Null
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Bughya\store\store.db'))) {
    $r = Say "لم أجد مكتبة بُغية على هذا الجهاز، والإضافةُ تبحث فيها.`n`nنصّب برنامج بُغية وأضف كتبك ودعه يقرؤها. أتريد أن أكمل التثبيت الآن مع ذلك؟" 'Warning' 'OKCancel'
    if ("$r" -ne 'OK') { exit 1 }
}
if (Get-ClaudeApp) {
    $r = Say "لكي تظهر نافذة التثبيت يجب أن يُفتح Claude من جديد.`n`nاضغط «موافق»، ثمّ أغلق Claude إغلاقًا تامًّا: انقر بالزرّ الأيمن على أيقونته قرب الساعة واختر Quit. وسأفتحه بعد ذلك وحدي." 'Information' 'OKCancel'
    if ("$r" -ne 'OK') { exit 1 }
    if ($env:BUGHYA_DRYRUN) { Write-Output "would wait for Claude to close, then run: $exe `"$($mcpb.FullName)`""; exit 0 }
    $deadline = (Get-Date).AddMinutes(10)
    while ((Get-ClaudeApp) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (Get-ClaudeApp) {
        Say "ما زال Claude مفتوحًا، فلم أكمل. انقر على هذا الملفّ مرّةً أخرى متى شئت." 'Warning' | Out-Null
        exit 1
    }
    Start-Sleep -Seconds 3
}
if ($env:BUGHYA_DRYRUN) { Write-Output "would run: $exe `"$($mcpb.FullName)`""; exit 0 }
Start-Process -FilePath $exe -ArgumentList ('"' + $mcpb.FullName + '"')
Say "يُفتح Claude الآن، وتظهر فيه نافذةٌ تسأل عن تثبيت «Bughya — بُغية».`n`nاضغط Install (تثبيت). وإن نبّهك أنّ الإضافة غيرُ موقَّعة فوافق." | Out-Null
