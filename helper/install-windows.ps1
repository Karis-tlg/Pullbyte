param(
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Pullbyte'
$RepoZip = 'https://github.com/Karis-tlg/Pullbyte/archive/refs/heads/main.zip'

function Refresh-UserPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Find-Python {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, '-3') }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    return $null
}

function Ensure-WingetPackage([string]$Command, [string]$PackageId) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "$Command is required and winget is not available. Install $Command, then run this installer again."
    }
    Write-Host "Installing $PackageId with winget..."
    & winget.exe install --id $PackageId -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install $PackageId." }
    Refresh-UserPath
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$PackageId was installed, but $Command is not available on PATH yet. Open a new PowerShell window and run the installer again."
    }
}

Ensure-WingetPackage 'ffmpeg.exe' 'Gyan.FFmpeg'
$pythonSpec = Find-Python
if (-not $pythonSpec) {
    Ensure-WingetPackage 'python.exe' 'Python.Python.3.13'
    Refresh-UserPath
    $pythonSpec = Find-Python
}
if (-not $pythonSpec) { throw 'Python 3.13 could not be found after installation.' }

$tempRoot = Join-Path $env:TEMP ("pullbyte-" + [Guid]::NewGuid().ToString('N'))
$zipPath = Join-Path $tempRoot 'pullbyte.zip'
$extractDir = Join-Path $tempRoot 'src'
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

Write-Host 'Downloading Pullbyte source...'
Invoke-WebRequest -Uri $RepoZip -OutFile $zipPath -UseBasicParsing
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
$sourceRoot = Get-ChildItem $extractDir -Directory | Select-Object -First 1
if (-not $sourceRoot) { throw 'Downloaded archive did not contain Pullbyte source.' }

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
foreach ($name in @('api', 'helper')) {
    $target = Join-Path $InstallDir $name
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Copy-Item (Join-Path $sourceRoot.FullName $name) $target -Recurse -Force
}
Copy-Item (Join-Path $sourceRoot.FullName 'requirements.txt') (Join-Path $InstallDir 'requirements.txt') -Force
Remove-Item $tempRoot -Recurse -Force

$venvDir = Join-Path $InstallDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'Creating Pullbyte helper environment...'
    if ($pythonSpec.Count -gt 1) {
        & $pythonSpec[0] $pythonSpec[1] -m venv $venvDir
    } else {
        & $pythonSpec[0] -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}

Write-Host 'Installing helper dependencies...'
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install Pullbyte helper dependencies.' }

$launcher = Join-Path $InstallDir 'start-helper.cmd'
$launcherText = "@echo off`r`ncd /d `"%LOCALAPPDATA%\Pullbyte`"`r`n`"%LOCALAPPDATA%\Pullbyte\.venv\Scripts\python.exe`" helper\run.py`r`n"
Set-Content -Path $launcher -Value $launcherText -Encoding ASCII
$protocolRoot = 'HKCU:\Software\Classes\pullbyte'
New-Item -Path $protocolRoot -Force | Out-Null
Set-Item -Path $protocolRoot -Value 'URL:Pullbyte Helper'
New-ItemProperty -Path $protocolRoot -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
$commandKey = Join-Path $protocolRoot 'shell\open\command'
New-Item -Path $commandKey -Force | Out-Null
Set-Item -Path $commandKey -Value ('"{0}" "%1"' -f $launcher)

Write-Host ''
Write-Host 'Pullbyte Helper is installed.' -ForegroundColor Green
Write-Host "Install directory: $InstallDir"
Write-Host "Downloads folder: $([Environment]::GetFolderPath('UserProfile'))\Downloads\Pullbyte"
Write-Host 'The Pullbyte website can now launch it with the pullbyte:// protocol.'

if (-not $NoStart) {
    Write-Host 'Starting Pullbyte Helper...'
    Start-Process -FilePath $launcher
}
