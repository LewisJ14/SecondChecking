<# Start only the known disposable lab services; never install or change schema. #>
$ErrorActionPreference = 'Stop'
$lab = 'C:\SecondChecking-Test'
if (-not (Test-Path -LiteralPath "$lab\settings.json")) { throw 'Synthetic lab is missing.' }
$database = "$lab\Database\mariadb-11.4.12-winx64\bin\mariadbd.exe"
$backend = "$lab\TestBackend.exe"
foreach ($item in @(@{Name='mariadbd'; Path=$database; Arguments="--defaults-file=$lab\database.ini"},
                     @{Name='TestBackend'; Path=$backend; Arguments=$null})) {
    $existing = @(Get-Process -Name $item.Name -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        if (@($existing | Where-Object { $_.Path -ne $item.Path }).Count -gt 0) {
            throw 'An unexpected service process exists; not starting another.'
        }
        continue
    }
    $parameters = @{FilePath=$item.Path; WorkingDirectory=$lab; WindowStyle='Hidden'; PassThru=$true}
    if ($item.Arguments) { $parameters.ArgumentList = $item.Arguments }
    $process = Start-Process @parameters
    Write-Output ("Started lab service {0}, PID {1}" -f $item.Name, $process.Id)
}
