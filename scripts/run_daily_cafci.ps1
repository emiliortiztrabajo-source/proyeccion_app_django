# run_daily_cafci.ps1
# Script: descarga diaria de planilla CAFCI, guarda historico y ejecuta ingest a DB
# Ajusta las rutas a tu entorno (python y repo)

Param(
    [string]$RepoPath = "C:\Users\usuario\Documents\GitHub\proyeccion_app_django",
    [string]$PythonExe = "C:\Users\usuario\Documents\GitHub\proyeccion_app_django\.venv\Scripts\python.exe",
    [string]$DataDir = "data",
    [string]$LogDir = "logs"
)

Set-StrictMode -Version Latest

try {
    Push-Location $RepoPath
} catch {
    Write-Error "No se pudo entrar a $RepoPath: $_"
    exit 2
}

# Crear dirs si no existen
New-Item -Path $DataDir -ItemType Directory -Force | Out-Null
New-Item -Path $LogDir -ItemType Directory -Force | Out-Null

$date = Get-Date -Format yyyyMMdd
$datedFile = Join-Path $DataDir ("cafci_planilla_$date.xlsx")
$currentFile = Join-Path $DataDir "cafci_planilla.xlsx"
$logFile = Join-Path $LogDir ("cafci_$date.log")

function Run-Cmd {
    param($exe, $args)
    $cmd = & $exe $args 2>&1 | Tee-Object -FilePath $logFile -Append
    return $LASTEXITCODE
}

# 1) Descargar planilla fechada
Write-Output "[INFO] Descargando planilla CAFCI a $datedFile" | Tee-Object -FilePath $logFile -Append
$downloadArgs = "manage.py download_cafci_planilla --path `"$datedFile`""
$rc = Run-Cmd $PythonExe $downloadArgs
if ($rc -ne 0) {
    Write-Error "Error descargando planilla (rc=$rc). Ver $logFile" | Tee-Object -FilePath $logFile -Append
    Pop-Location
    exit $rc
}

# 2) Copiar a current
try {
    Copy-Item -Path $datedFile -Destination $currentFile -Force
    Write-Output "[INFO] Copiado $datedFile -> $currentFile" | Tee-Object -FilePath $logFile -Append
} catch {
    Write-Error "No se pudo copiar a current: $_" | Tee-Object -FilePath $logFile -Append
}

# 3) Ingest a DB (usa la planilla fechada)
Write-Output "[INFO] Ejecutando ingest a DB usando $datedFile" | Tee-Object -FilePath $logFile -Append
$ingestArgs = "manage.py ingest_cafci_planilla --path `"$datedFile`""
$rc = Run-Cmd $PythonExe $ingestArgs
if ($rc -ne 0) {
    Write-Error "Error en ingest (rc=$rc). Ver $logFile" | Tee-Object -FilePath $logFile -Append
    Pop-Location
    exit $rc
}

Write-Output "[INFO] Proceso completado OK." | Tee-Object -FilePath $logFile -Append
Pop-Location
exit 0
