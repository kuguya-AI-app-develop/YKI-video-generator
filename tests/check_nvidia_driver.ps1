#requires -Version 5.1
# Exercise the real installer preflight without running installation or downloads.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Bootstrap = Join-Path $Root 'scripts/bootstrap.ps1'
$Source = [IO.File]::ReadAllText($Bootstrap)
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseInput($Source, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count -ne 0) { throw "Invalid bootstrap PowerShell syntax: $ParseErrors" }
$Start = $Ast.Find({ param($Node)
    $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $Node.Left.ToString() -eq '$GpuSummary'
}, $true)
$End = $Ast.Find({ param($Node)
    $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $Node.Left.ToString() -eq '$GpuRows'
}, $true)
if ($null -eq $Start -or $null -eq $End) { throw 'Installer preflight boundaries changed; update this test harness.' }
$Check = [scriptblock]::Create($Source.Substring($Start.Extent.StartOffset, $End.Extent.StartOffset - $Start.Extent.StartOffset))

function Invoke-TestNvidia {
    $global:LASTEXITCODE = [int]$script:Fixture.exit_code
    return ($script:Fixture.stdout -split "`n")
}
$NvidiaSmi = [pscustomobject]@{ Source = 'Invoke-TestNvidia' }
$Fixtures = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fixtures/nvidia-smi-headers.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Failures = @()
foreach ($script:Fixture in $Fixtures) {
    $Failure = $null
    try { . $Check } catch { $Failure = $_.Exception.Message }
    if ($Fixture.compatible) {
        if ($null -ne $Failure) { $Failures += "$($Fixture.name): $Failure" }
    } elseif ($null -eq $Failure) {
        $Failures += "$($Fixture.name): incompatible driver was accepted"
    } elseif (-not $Failure.Contains($Fixture.error)) {
        $Failures += "$($Fixture.name): wrong failure: $Failure"
    }
}
if ($Failures.Count -gt 0) {
    $Failures | ForEach-Object { Write-Output $_ }
    exit 1
}
Write-Output "Installer driver preflight: $($Fixtures.Count) cases passed."
