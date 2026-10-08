# Invoke through Windows-MCP PowerShell after all selected writers have closed.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$VeloRepository,
    [Parameter(Mandatory=$true)][string]$PolicyPath,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [Parameter(Mandatory=$true)][string[]]$Files,
    [Parameter(Mandatory=$true)][string]$BatchId,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string[]]$References,
    [switch]$ProducerComplete,
    [switch]$ProducerQuiescent
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not $ProducerComplete -or -not $ProducerQuiescent) { throw 'Finish and close all producer outputs before exporting.' }
if ($BatchId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$') { throw 'Invalid batch identity.' }
foreach ($path in @($VeloRepository,$PolicyPath,$OutputRoot,$SourceRoot,$EvidenceDirectory)+$Files) {
    if (-not [IO.Path]::IsPathRooted($path)) { throw "Use explicit absolute paths: $path" }
}
$source=(Get-Item -LiteralPath $SourceRoot).FullName.TrimEnd('\')
$records=@(foreach($path in $Files) {
    $file=Get-Item -LiteralPath $path -Force
    if ($file -is [IO.DirectoryInfo] -or -not $file.FullName.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)) { throw "File must be within SourceRoot: $path" }
    [ordered]@{path=$file.FullName; relative_path=$file.FullName.Substring($source.Length+1).Replace('\','/')
        size=$file.Length; sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); complete=$true}
})
$null=New-Item -ItemType Directory -Path $EvidenceDirectory -Force
$manifestPath=Join-Path $EvidenceDirectory ($BatchId+'.export.json')
if (Test-Path -LiteralPath $manifestPath) { throw 'Export evidence exists; use a new batch identity.' }
$manifest=[ordered]@{schema='velo.artifact-export.v1'; producer='Windows-MCP'; batch_id=$BatchId
    source_root=$source; producer_complete=$true; producer_quiescent=$true; references=$References; files=$records}
[IO.File]::WriteAllText($manifestPath,($manifest|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
& (Join-Path $VeloRepository 'export_transfer_artifacts.ps1') -ManifestPath $manifestPath -PolicyPath $PolicyPath -OutputRoot $OutputRoot
