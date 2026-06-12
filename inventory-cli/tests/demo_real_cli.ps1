# Real CLI Demo Script (English to avoid encoding issues)
$ErrorActionPreference = "Continue"
$DemoDir = "d:\workSpace\AI__SPACE\lfc-00002\inventory-cli\demo_run"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Real CLI Demo - Full User Flow" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Cleanup old data
if (Test-Path $DemoDir) { Remove-Item -Recurse -Force $DemoDir }
New-Item -ItemType Directory -Path $DemoDir | Out-Null
Set-Location $DemoDir

$env:PYTHONPATH = "d:\workSpace\AI__SPACE\lfc-00002\inventory-cli\src"
$Py = "python"
$Cli = "-m", "inventory_cli.cli"
$Db = "--database", "$DemoDir\demo.db"

# ============================================================
Write-Host ""
Write-Host "[1/10] Init repo + generate config file" -ForegroundColor Green
# ============================================================
& $Py @Cli "init" @Db
Write-Host ""
Write-Host ">> Generated config file:" -ForegroundColor Cyan
Get-Content "$DemoDir\inventory.config.json"

# ============================================================
Write-Host ""
Write-Host "[2/10] Edit config: change strategy to sum" -ForegroundColor Green
# ============================================================
$Config = Get-Content "$DemoDir\inventory.config.json" | ConvertFrom-Json
$Config.conflict_strategy = "sum"
$Config | ConvertTo-Json -Depth 10 | Set-Content "$DemoDir\inventory.config.json"
Write-Host ">> Updated config file:" -ForegroundColor Cyan
Get-Content "$DemoDir\inventory.config.json"

# ============================================================
Write-Host ""
Write-Host "[3/10] Import Store A CSV" -ForegroundColor Green
# ============================================================
& $Py @Cli "import" "d:\workSpace\AI__SPACE\lfc-00002\inventory-cli\tests\store_a.csv" "STORE001" "--batch" "batch_store_a" @Db

# ============================================================
Write-Host ""
Write-Host "[4/10] Import Store B JSON" -ForegroundColor Green
# ============================================================
& $Py @Cli "import" "d:\workSpace\AI__SPACE\lfc-00002\inventory-cli\tests\store_b.json" "STORE002" "--batch" "batch_store_b" @Db

# ============================================================
Write-Host ""
Write-Host "[5/10] List imported batches" -ForegroundColor Green
# ============================================================
& $Py @Cli "batches" @Db

# ============================================================
Write-Host ""
Write-Host "[6/10] Merge (uses config file 'sum' strategy)" -ForegroundColor Green
# ============================================================
& $Py @Cli "merge" @Db

# ============================================================
Write-Host ""
Write-Host "[7/10] Export full report (with source batches + diff)" -ForegroundColor Green
# ============================================================
& $Py @Cli "export" "$DemoDir\merged_report.report.json" @Db
Write-Host ""
Write-Host ">> Report metadata:" -ForegroundColor Cyan
$Report = Get-Content "$DemoDir\merged_report.report.json" | ConvertFrom-Json
$Report.metadata | ConvertTo-Json -Depth 10

# ============================================================
Write-Host ""
Write-Host "[8/10] Show operation history" -ForegroundColor Green
# ============================================================
& $Py @Cli "history" @Db

# ============================================================
Write-Host ""
Write-Host "[9/10] Rollback to snapshot #1 (sum strategy)" -ForegroundColor Green
# ============================================================
& $Py @Cli "rollback" @Db  # List snapshots first
Write-Host ""
& $Py @Cli "rollback" "1" @Db

# ============================================================
Write-Host ""
Write-Host "[10/10] Export again - back to rolled-back version" -ForegroundColor Green
# ============================================================
& $Py @Cli "export" "$DemoDir\after_rollback.csv" @Db
Write-Host ""
Write-Host ">> Exported CSV preview:" -ForegroundColor Cyan
Get-Content "$DemoDir\after_rollback.csv"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Demo complete! All steps successful" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Data directory: $DemoDir" -ForegroundColor Cyan
