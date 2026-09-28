# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
  Tag a partsmith release, wait for the GHCR image, and deploy it to ZimaOS.

.DESCRIPTION
  1. Clones main, checks pyproject.toml matches -Version and CI is green.
  2. Warns if CHANGELOG still marks the version "Unreleased".
  3. Creates + pushes annotated tag v<Version> (skipped if it already exists).
  4. Waits for the Release workflow (release.yml) to publish
     ghcr.io/jlay2026/partsmith:<Version>.
  5. Over SSH: pulls the image, bumps the tag in ZimaOS's app compose
     (backup kept), recreates the container, and checks /health reports
     <Version>.

  Requires: git, gh (authenticated), ssh to the ZimaOS host.

.EXAMPLE
  .\release-deploy.ps1 -ZimaHost user@zimaboard

.EXAMPLE
  # Redeploy an existing tag without re-tagging
  .\release-deploy.ps1 -ZimaHost user@zimaboard -SkipTag
#>
param(
    [Parameter(Mandatory = $true)][string]$ZimaHost,
    [string]$Version = "0.4.0",
    [string]$Repo = "JLay2026/partsmith",
    [string]$ComposePath = "/var/lib/casaos/apps/partsmith/docker-compose.yml",
    [switch]$SkipTag,
    [switch]$SkipDeploy,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Tag = "v$Version"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

foreach ($cmd in "git", "gh", "ssh") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found on PATH" }
}
gh auth status *> $null; Check "gh auth status (run 'gh auth login')"

# -- 1-3. Tag ---------------------------------------------------------
if (-not $SkipTag) {
    $work = Join-Path $env:TEMP "partsmith-release-$Version"
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    Step "Cloning $Repo"
    git clone --quiet "https://github.com/$Repo.git" $work; Check "git clone"
    Push-Location $work
    try {
        $pyVer = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
        if ($pyVer -ne $Version) { throw "pyproject.toml says $pyVer, expected $Version" }

        if (Select-String -Path CHANGELOG.md -Pattern "^## \[$([regex]::Escape($Version))\] .*Unreleased" -Quiet) {
            Write-Warning "CHANGELOG.md still marks [$Version] as Unreleased."
            if (-not $Force) {
                $ans = Read-Host "Tag anyway? (y/N)"
                if ($ans -notmatch '^[yY]') { throw "Aborted: finalize CHANGELOG first (or rerun with -Force)" }
            }
        }

        if (git ls-remote --tags origin "refs/tags/$Tag") {
            Write-Host "$Tag already exists on origin; skipping tag creation."
        } else {
            $sha = (git rev-parse HEAD).Trim()
            Step "Checking CI on main @ $($sha.Substring(0,7))"
            $runs = gh run list --repo $Repo --commit $sha --json name,status,conclusion | ConvertFrom-Json
            Check "gh run list"
            $bad = $runs | Where-Object { $_.conclusion -ne "success" }
            if (-not $runs -or $bad) {
                $runs | Format-Table name, status, conclusion
                if (-not $Force) { throw "CI not green (or still running) on $sha. Rerun later or use -Force." }
            }
            Step "Tagging $Tag"
            git -c user.name="$(gh api user --jq .login)" -c user.email="noreply@github.com" `
                tag -a $Tag -m "partsmith $Tag"; Check "git tag"
            git push origin $Tag; Check "git push tag"
        }
    } finally { Pop-Location }
}

# -- 4. Wait for the image ---------------------------------------------
Step "Waiting for Release workflow on $Tag"
$runId = $null
for ($i = 0; $i -lt 36 -and -not $runId; $i++) {
    $runId = (gh run list --repo $Repo --workflow release.yml --branch $Tag `
              --json databaseId --limit 1 | ConvertFrom-Json).databaseId
    if (-not $runId) { Start-Sleep 10 }
}
if (-not $runId) { throw "No Release run found for $Tag after 6 minutes" }
gh run watch $runId --repo $Repo --exit-status; Check "Release workflow (run $runId)"
Write-Host "Image published: ghcr.io/jlay2026/partsmith:$Version" -ForegroundColor Green

if ($SkipDeploy) { Write-Host "SkipDeploy set; done."; return }

# -- 5. Deploy on ZimaOS -----------------------------------------------
Step "Deploying $Version to $ZimaHost"
$remote = @"
set -euo pipefail
IMG=ghcr.io/jlay2026/partsmith:$Version
F=$ComposePath
if [ ! -f "`$F" ]; then
  echo "ZimaOS compose not found at `$F."
  echo "Set the partsmith Tag to $Version in the ZimaOS dashboard instead."
  exit 2
fi
sudo docker pull "`$IMG"
sudo cp "`$F" "`$F.bak-`$(date +%Y%m%d%H%M%S)"
sudo sed -i -E 's#(ghcr\.io/jlay2026/partsmith:)[^" ]+#\1$Version#' "`$F"
grep -n 'ghcr.io/jlay2026/partsmith:' "`$F"
cd "`$(dirname "`$F")"
sudo docker compose -f "`$F" up -d
for i in `$(seq 1 45); do
  if curl -fsS http://127.0.0.1:8123/health 2>/dev/null | grep -q '"$Version"'; then
    curl -fsS http://127.0.0.1:8123/health; echo
    echo "DEPLOYED $Version"
    exit 0
  fi
  sleep 2
done
echo "Health check never reported $Version. Recent logs:"
sudo docker logs --tail 50 partsmith
exit 1
"@ -replace "`r", ""
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote))
ssh -t $ZimaHost "echo $b64 | base64 -d | bash"; Check "Remote deploy"
Write-Host "`npartsmith $Version is live on $ZimaHost." -ForegroundColor Green
Write-Host "Rollback: restore the .bak next to $ComposePath and 'docker compose up -d'."
