#requires -Version 5.1
<#
    RebootAppTask.ps1 - регистрация задачи автозапуска RebootAppScript
    в Планировщике заданий Windows.

    Запускается из install.bat / control.bat / uninstall.bat.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Uninstall', 'Status', 'Start', 'Stop')]
    [string]$Action,

    [string]$TaskName = 'RebootAppScript',
    [string]$PythonPath,
    [string]$ScriptPath,

    [ValidateSet('Logon', 'Boot')]
    [string]$Mode = 'Logon',

    [string]$User = '',

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

if (-not $User) {
    $domain = $env:USERDOMAIN
    if (-not $domain) { $domain = $env:COMPUTERNAME }
    $User = '{0}\{1}' -f $domain, $env:USERNAME
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Fail([string]$Message, [int]$Code = 1) {
    Write-Host "[ОШИБКА] $Message" -ForegroundColor Red
    exit $Code
}

function Show-Header {
    Write-Host ''
    Write-Host "RebootAppScript - задача автозапуска '$TaskName'" -ForegroundColor Cyan
    Write-Host ''
}

switch ($Action) {
    'Install' {
        Show-Header

        if (-not $PythonPath) { Fail 'Не указан путь к pythonw.exe (-PythonPath)' }
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            Fail "Не найден pythonw.exe: $PythonPath"
        }
        if (-not $ScriptPath) { Fail 'Не указан путь к script.py (-ScriptPath)' }
        if (-not (Test-Path -LiteralPath $ScriptPath)) {
            Fail "Не найден script.py: $ScriptPath"
        }

        $scriptDirectory = Split-Path -Parent $ScriptPath
        $arguments = '"{0}" --daemon' -f $ScriptPath

        if ($Mode -eq 'Boot') {
            $trigger = New-ScheduledTaskTrigger -AtStartup
            $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
            $modeText = 'при запуске компьютера (SYSTEM, без входа пользователя)'
        }
        else {
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
            $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
            $modeText = "при входе пользователя $User"
        }

        $taskAction = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $scriptDirectory
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 10 `
            -RestartInterval (New-TimeSpan -Minutes 1)

        Write-Host '  Исполняемый файл: ' -NoNewline; Write-Host $PythonPath
        Write-Host '  Аргументы:        ' -NoNewline; Write-Host $arguments
        Write-Host '  Рабочая папка:    ' -NoNewline; Write-Host $scriptDirectory
        Write-Host '  Триггер:          ' -NoNewline; Write-Host $modeText
        Write-Host '  Права:            ' -NoNewline; Write-Host 'наивысшие (без запроса UAC)'
        Write-Host ''

        if ($DryRun) {
            Write-Host '[DRY RUN] Задача не регистрируется.' -ForegroundColor Yellow
            exit 0
        }

        if (-not (Test-Administrator)) {
            Fail 'Для регистрации задачи нужны права администратора. Запустите install.bat от имени администратора.'
        }

        try {
            Register-ScheduledTask `
                -TaskName $TaskName `
                -Description 'Ежедневный перезапуск приложения (RebootAppScript)' `
                -Action $taskAction `
                -Trigger $trigger `
                -Settings $settings `
                -Principal $principal `
                -Force `
                -ErrorAction Stop | Out-Null
        }
        catch {
            Fail ("Не удалось зарегистрировать задачу: {0}" -f $_.Exception.Message)
        }

        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) { Fail 'Задача не появилась в планировщике после регистрации.' }

        Write-Host "[OK] Задача '$TaskName' зарегистрирована." -ForegroundColor Green
        Write-Host "     Состояние: $($task.State)"
        exit 0
    }

    'Uninstall' {
        Show-Header

        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "Задача '$TaskName' не зарегистрирована - удалять нечего." -ForegroundColor Yellow
            exit 0
        }

        if (-not (Test-Administrator)) {
            Fail 'Для удаления задачи нужны права администратора.'
        }

        if ($task.State -eq 'Running') {
            try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch { }
            Start-Sleep -Seconds 2
        }

        $removed = $false
        for ($attempt = 1; $attempt -le 5; $attempt++) {
            try {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
                $removed = $true
                break
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }

        if (-not $removed) { Fail 'Не удалось удалить задачу. Возможно, она ещё выполняется.' }

        Write-Host "[OK] Задача '$TaskName' удалена." -ForegroundColor Green
        exit 0
    }

    'Status' {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "Задача автозапуска '$TaskName' не зарегистрирована." -ForegroundColor Yellow
            exit 3
        }

        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue

        $lastRun = 'ещё не запускалась'
        if ($info -and $info.LastRunTime -and $info.LastRunTime.Year -gt 2000) {
            $lastRun = $info.LastRunTime.ToString('dd.MM.yyyy HH:mm:ss')
        }

        $nextRun = 'при следующем входе пользователя'
        if ($info -and $info.NextRunTime -and $info.NextRunTime.Year -gt 2000) {
            $nextRun = $info.NextRunTime.ToString('dd.MM.yyyy HH:mm:ss')
        }

        $resultText = 'нет данных'
        if ($info) {
            $result = $info.LastTaskResult
            if ($result -eq 0) {
                $resultText = '0 (успешно)'
            }
            else {
                $resultText = '{0} (0x{0:X8})' -f $result
            }
        }

        Write-Host 'Задача автозапуска:' -ForegroundColor Cyan
        Write-Host "  Имя:              $TaskName"
        Write-Host "  Состояние:        $($task.State)"
        Write-Host "  Последний запуск: $lastRun"
        Write-Host "  Результат:        $resultText"
        Write-Host "  Следующий запуск: $nextRun"
        Write-Host "  Действие:         $($task.Actions[0].Execute) $($task.Actions[0].Arguments)"
        exit 0
    }

    'Start' {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "Задача '$TaskName' не зарегистрирована." -ForegroundColor Yellow
            exit 3
        }
        if ($task.State -eq 'Running') {
            Write-Host "Задача '$TaskName' уже запущена." -ForegroundColor Yellow
            exit 0
        }
        try {
            Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
            Write-Host "[OK] Задача '$TaskName' запущена." -ForegroundColor Green
            exit 0
        }
        catch {
            Fail ("Не удалось запустить задачу: {0}" -f $_.Exception.Message)
        }
    }

    'Stop' {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "Задача '$TaskName' не зарегистрирована." -ForegroundColor Yellow
            exit 3
        }
        if ($task.State -ne 'Running') {
            Write-Host 'Задача уже остановлена.' -ForegroundColor Yellow
            exit 0
        }
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
            Write-Host "[OK] Задача '$TaskName' остановлена." -ForegroundColor Green
            exit 0
        }
        catch {
            Fail ("Не удалось остановить задачу: {0}" -f $_.Exception.Message)
        }
    }
}
