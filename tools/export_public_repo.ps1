<##
.SYNOPSIS
Exports a clean, no-history public release tree from this private working tree.

.DESCRIPTION
The target must be empty unless -Force is supplied. The script never copies
.git metadata, .env files, runtime output, raw bank/source-doc inputs, course
submission material, model caches, node_modules, backups, patches, or ad-hoc
debug/fix scripts. Run it into a freshly cloned empty GitHub repository, then
inspect the result before the first commit.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [switch]$Force
)

$source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = [System.IO.Path]::GetFullPath($Destination)

if ($source -eq $target) {
    throw 'Destination must be different from the source repository.'
}

if (Test-Path -LiteralPath $target) {
    $existing = Get-ChildItem -LiteralPath $target -Force
    if ($existing.Count -gt 0 -and -not $Force) {
        throw 'Destination is not empty. Use a fresh clone or explicitly pass -Force after inspection.'
    }
} else {
    New-Item -ItemType Directory -Path $target | Out-Null
}

$excludedDirectories = @(
    '.git', '.ai', '.venv', 'venv', 'node_modules', 'dist', 'output', '__pycache__',
    '.pytest_cache', '.ruff_cache', 'bank', 'data/source-docs', 'doc', 'deliverables', 'screenshots'
)
$excludedFileNames = @('AGENTS.md', 'CLAUDE.md', '.env')
$excludedSuffixes = @('.backup', '.patch', '.tar.gz', '.zip', '.db', '.pyc')
$excludedPrefixes = @('debug_', 'fix_', 'temp_', 'check_')

function Test-ExcludedFile([System.IO.FileInfo]$File) {
    $relative = $File.FullName.Substring($source.Length).TrimStart('\', '/') -replace '\\', '/'
    if ($relative.StartsWith('doc/skills/', [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    $segments = $relative -split '/'
    foreach ($directory in $excludedDirectories) {
        if ($segments -contains $directory) {
            return $true
        }
    }
    if ($segments | Where-Object { $_.EndsWith('.egg-info', [System.StringComparison]::OrdinalIgnoreCase) }) {
        return $true
    }
    if ($excludedFileNames -contains $File.Name) { return $true }
    foreach ($suffix in $excludedSuffixes) {
    if ($File.Name.Contains($suffix, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    foreach ($prefix in $excludedPrefixes) {
        if ($File.Name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    if ($File.Name.EndsWith('_new.py', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    if ($File.Name.EndsWith('_enhanced.py', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    if ($File.Name -match '(?i)(^|[_-])backup([_.-]|$)') { return $true }
    if ($File.Name -in @('test_grounding_debug.py', 'test_client.py', 'generate_demo_report.py', 'write_demo_script.py')) {
        return $true
    }
    return $false
}

$copied = 0
Get-ChildItem -LiteralPath $source -Recurse -File -Force | ForEach-Object {
    if (Test-ExcludedFile $_) { return }
    $relative = $_.FullName.Substring($source.Length).TrimStart('\', '/')
    $destinationFile = Join-Path $target $relative
    $destinationDirectory = Split-Path -Parent $destinationFile
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destinationFile -Force
    $script:copied++
}

Write-Host "Exported $copied files to $target"
Write-Host 'Next: inspect files, run python tools/public_release_check.py, then initialize/commit the target repository.'
