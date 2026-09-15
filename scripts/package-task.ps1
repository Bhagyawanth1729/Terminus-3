# Package a Terminus 3 task from tasks/ into ready-to-submit/
#
# Usage:
#   .\scripts\package-task.ps1 -TaskName your-task-name
#   .\scripts\package-task.ps1 -TaskName your-task-name -SubmitOnly
#   .\scripts\package-task.ps1 -TaskPath tasks\your-task-name

param(
    [Parameter(Mandatory = $false)]
    [string]$TaskName,

    [Parameter(Mandatory = $false)]
    [string]$TaskPath,

    [switch]$SubmitOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TasksDir = Join-Path $RepoRoot "tasks"
$OutDir = Join-Path $RepoRoot "ready-to-submit"

if ($TaskPath) {
    $TaskDir = Resolve-Path $TaskPath
    $TaskName = Split-Path -Leaf $TaskDir
} elseif ($TaskName) {
    $TaskDir = Join-Path $TasksDir $TaskName
} else {
    Write-Error "Provide -TaskName or -TaskPath"
}

if (-not (Test-Path $TaskDir)) {
    Write-Error "Task folder not found: $TaskDir"
}

$Required = @(
    "task.toml",
    "instruction.md",
    "environment",
    "solution",
    "tests"
)

foreach ($item in $Required) {
    if (-not (Test-Path (Join-Path $TaskDir $item))) {
        Write-Error "Missing required item: $item"
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$PreviewZip = Join-Path $OutDir "$TaskName-preview.zip"
$SubmitZip = Join-Path $OutDir "$TaskName-submit.zip"

if (Test-Path $PreviewZip) { Remove-Item $PreviewZip -Force }
if (Test-Path $SubmitZip) { Remove-Item $SubmitZip -Force }

if (-not $SubmitOnly) {
    # Local preview: your-task-name/ inside the zip
    $StagingPreview = Join-Path $env:TEMP "terminus3-pack-$TaskName-preview"
    if (Test-Path $StagingPreview) { Remove-Item $StagingPreview -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Join-Path $StagingPreview $TaskName) | Out-Null

    foreach ($item in $Required) {
        $dest = Join-Path (Join-Path $StagingPreview $TaskName) $item
        Copy-Item -Recurse -Force (Join-Path $TaskDir $item) $dest
    }

    Compress-Archive -Path (Join-Path $StagingPreview $TaskName) -DestinationPath $PreviewZip
    Remove-Item $StagingPreview -Recurse -Force
    Write-Host "Preview zip: $PreviewZip"
}

# Platform submission: flat layout at zip root (no wrapper folder)
$StagingSubmit = Join-Path $env:TEMP "terminus3-pack-$TaskName-submit"
if (Test-Path $StagingSubmit) { Remove-Item $StagingSubmit -Recurse -Force }
New-Item -ItemType Directory -Force -Path $StagingSubmit | Out-Null

foreach ($item in $Required) {
    Copy-Item -Recurse -Force (Join-Path $TaskDir $item) (Join-Path $StagingSubmit $item)
}

Compress-Archive -Path (Join-Path $StagingSubmit "*") -DestinationPath $SubmitZip
Remove-Item $StagingSubmit -Recurse -Force
Write-Host "Submit zip:  $SubmitZip"
Write-Host "Done. Upload *-submit.zip to Terminus-3-Prod (no rubrics.txt / README.md inside)."
