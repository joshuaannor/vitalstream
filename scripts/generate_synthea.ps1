<#
.SYNOPSIS
  Generates synthetic FHIR R4 patient bundles with Synthea (no real patient data).

.DESCRIPTION
  1. Downloads a pinned Synthea release into tools\synthea (once) and checks its SHA-256.
  2. Deletes any previous output in data\raw\synthea (it is fully regenerable).
  3. Runs Synthea with a fixed seed, fixed dates and one thread, so every run gives
     byte-for-byte identical files.
  Output: data\raw\synthea\fhir\*.json, one Bundle per patient.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\generate_synthea.ps1
#>
param(
    [int]$Patients = 100,
    [int]$Seed = 42,
    [string]$ReferenceDate = "20260101"   # YYYYMMDD; fixed so output is reproducible
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is very slow in PS 5.1 with the progress bar

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$Version   = "v4.0.0"
$JarUrl    = "https://github.com/synthetichealth/synthea/releases/download/$Version/synthea-with-dependencies.jar"
$JarSha256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
$JarDir    = Join-Path $RepoRoot "tools\synthea"
$Jar       = Join-Path $JarDir "synthea-with-dependencies-$Version.jar"
$OutDir    = Join-Path $RepoRoot "data\raw\synthea"

# --- 1. Download the pinned release once ---------------------------------
if (-not (Test-Path $Jar)) {
    New-Item -ItemType Directory -Force $JarDir | Out-Null
    Write-Host "Downloading Synthea $Version (~200 MB) from GitHub..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $JarUrl -OutFile $Jar -UseBasicParsing
}

$actual = (Get-FileHash $Jar -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $JarSha256) {
    Remove-Item $Jar
    throw "Checksum mismatch for Synthea jar (got $actual). Deleted it; run the script again."
}
Write-Host "Synthea $Version jar verified (SHA-256 OK)."

# --- 2. Start from a clean output folder ---------------------------------
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }

# --- 3. Run Synthea ------------------------------------------------------
$javaArgs = @(
    "-jar", $Jar,
    "-p", $Patients,                 # number of living patients (deceased ones are added on top)
    "-s", $Seed,                     # population seed
    "-cs", $Seed,                    # clinician seed
    "-r", $ReferenceDate,            # "today" for the simulation (used for ages)
    "-e", $ReferenceDate,            # stop simulating here; without it Synthea runs to the real date
    "--exporter.baseDirectory", ($OutDir -replace '\\', '/'),
    "--exporter.fhir.export", "true",
    "--exporter.hospital.fhir.export", "false",      # skip shared Organization/Location bundles
    "--exporter.practitioner.fhir.export", "false",  # skip shared Practitioner bundles
    "--exporter.csv.export", "false",
    "--exporter.years_of_history", "10",             # keeps files small
    "--generate.thread_pool_size", "1",              # single thread: multi-threaded runs vary slightly
    "Massachusetts"
)
Write-Host "Generating $Patients patients (seed $Seed, reference date $ReferenceDate)..."
& java @javaArgs
if ($LASTEXITCODE -ne 0) { throw "Synthea failed with exit code $LASTEXITCODE" }

# --- 4. Summary ----------------------------------------------------------
$files = Get-ChildItem (Join-Path $OutDir "fhir") -Filter *.json
$sizeMb = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "Done: $($files.Count) bundles, $sizeMb MB in $OutDir\fhir"
