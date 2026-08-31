# 第二の脳 / SOT21操作盤 を最新版に更新する。
# GitHubから最新のZIPを取得し、コードのフォルダだけ入れ替える。
# データベース（~/.second_brain/brain.db）と config.json は触らない。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$zipUrl = 'https://github.com/kaidoki-lab/second-brain/archive/refs/heads/main.zip'
$work = Join-Path $env:TEMP ('sb_update_' + [Guid]::NewGuid().ToString('N'))

Write-Host ''
Write-Host '============================================'
Write-Host '  第二の脳 を最新版に更新します'
Write-Host '============================================'
Write-Host ''

try {
    New-Item -ItemType Directory -Path $work -Force | Out-Null

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch { }

    Write-Host '[1/3] ダウンロード中...'
    $zip = Join-Path $work 'main.zip'
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing

    Write-Host '[2/3] 展開中...'
    Expand-Archive -Path $zip -DestinationPath $work -Force
    $src = Join-Path $work 'second-brain-main'
    if (-not (Test-Path $src)) {
        throw '展開したフォルダが見つかりません。'
    }

    Write-Host '[3/3] 入れ替え中...'
    foreach ($name in @('second_brain', 'SOT21_Controller')) {
        $from = Join-Path $src $name
        $to = Join-Path $root $name
        if (-not (Test-Path $from)) { continue }
        if (-not (Test-Path $to)) { New-Item -ItemType Directory -Path $to | Out-Null }

        # config.json はユーザーの設定なので上書きしない
        Get-ChildItem -Path $from -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($from.Length).TrimStart('\')
            if ($relative -eq 'config.json' -and (Test-Path (Join-Path $to $relative))) {
                Write-Host ('    設定は残しました: ' + $name + '\config.json')
                return
            }
            $target = Join-Path $to $relative
            $parent = Split-Path -Parent $target
            if (-not (Test-Path $parent)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            Copy-Item -Path $_.FullName -Destination $target -Force
        }
    }
    $readme = Join-Path $src 'README.md'
    if (Test-Path $readme) { Copy-Item -Path $readme -Destination $root -Force }

    $version = '不明'
    $initFile = Join-Path $root 'second_brain\secondbrain\__init__.py'
    if (Test-Path $initFile) {
        $line = Select-String -Path $initFile -Pattern 'RELEASE\s*=\s*"(.+)"'
        if ($line) { $version = $line.Matches[0].Groups[1].Value }
    }

    Write-Host ''
    Write-Host '完了しました。'
    Write-Host ('  バージョン: ' + $version)
    Write-Host ''
    Write-Host '  second_brain\start.bat をダブルクリックすると起動します。'
    Write-Host '  ※ 起動中の黒い画面があれば、先に閉じてください。'
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host '更新に失敗しました:' -ForegroundColor Red
    Write-Host ('  ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ''
    Write-Host '  インターネットに接続できているか確認してください。'
    Write-Host '  それでも駄目なら、GitHubから手動でZIPを取得してください:'
    Write-Host '    https://github.com/kaidoki-lab/second-brain'
    Write-Host ''
}
finally {
    if (Test-Path $work) {
        Remove-Item -Path $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
