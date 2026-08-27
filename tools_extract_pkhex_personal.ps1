param(
    [string]$RepositoryRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$dllPath = Join-Path $RepositoryRoot "engine\publish\PKHeX.Core.dll"
$targets = @(
    @{ Output = "data\pkhex_personal_uu.bin"; Resource = "PKHeX.Core.Resources.byte.personal.personal_uu"; RecordSize = 0x54 },
    @{ Output = "data\pkhex_personal_b2w2.bin"; Resource = "PKHeX.Core.Resources.byte.personal.personal_b2w2"; RecordSize = 0x4C }
)

if (-not (Test-Path -LiteralPath $dllPath)) {
    throw "No existe el PKHeX.Core.dll publicado: $dllPath"
}

$assembly = [System.Reflection.Assembly]::LoadFrom($dllPath)
foreach ($target in $targets) {
    $outputPath = Join-Path $RepositoryRoot $target.Output
    $resourceName = $target.Resource
    $recordSize = [int]$target.RecordSize
    $stream = $assembly.GetManifestResourceStream($resourceName)
    if ($null -eq $stream) {
        throw "PKHeX.Core.dll no contiene el recurso $resourceName"
    }
    try {
        $memory = [System.IO.MemoryStream]::new()
        try {
            $stream.CopyTo($memory)
            $bytes = $memory.ToArray()
        }
        finally {
            $memory.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }

    if ($bytes.Length -eq 0 -or ($bytes.Length % $recordSize) -ne 0) {
        throw "$resourceName no contiene registros de 0x$($recordSize.ToString('X')) bytes."
    }

    [System.IO.File]::WriteAllBytes($outputPath, $bytes)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $sha = $hasher.ComputeHash($bytes)
    }
    finally {
        $hasher.Dispose()
    }
    Write-Output ("Extraído {0} bytes en {1}" -f $bytes.Length, $outputPath)
    $shaText = ([System.BitConverter]::ToString($sha)).Replace("-", "")
    Write-Output ("SHA-256 {0}" -f $shaText)
}
