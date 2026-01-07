# PowerShell script to set up Windows Task Scheduler for daily journaling
# Run this script as Administrator

$scriptPath = "d:\projects\notion_journal\notion_journal.py"
$taskName = "Daily Notion Journal"
$taskDescription = "Automatically creates a daily journal entry in Notion with Cursor activity and GitHub commits"

# Try to find conda python
$condaPython = $null
$possiblePaths = @(
    "$env:USERPROFILE\anaconda3\envs\notion-journal\python.exe",
    "$env:USERPROFILE\miniconda3\envs\notion-journal\python.exe",
    "$env:USERPROFILE\AppData\Local\Continuum\anaconda3\envs\notion-journal\python.exe",
    "C:\ProgramData\Anaconda3\envs\notion-journal\python.exe",
    "C:\ProgramData\Miniconda3\envs\notion-journal\python.exe"
)

foreach ($path in $possiblePaths) {
    if (Test-Path $path) {
        $condaPython = $path
        Write-Host "Found Conda Python at: $condaPython"
        break
    }
}

if (-not $condaPython) {
    # Try to find it via conda
    try {
        $condaInfo = conda info --envs 2>$null
        if ($condaInfo) {
            Write-Host "Please activate the 'notion-journal' environment and run:"
            Write-Host "  where python"
            Write-Host "Then update this script with the full path."
        }
    } catch {
        Write-Host "Could not find conda. Please provide the full path to Python in the notion-journal environment."
    }
    
    $condaPython = Read-Host "Enter full path to Python in notion-journal environment (or press Enter to use 'python')"
    if ([string]::IsNullOrWhiteSpace($condaPython)) {
        $condaPython = "python"
    }
}

# Get schedule time from user
$scheduleTime = Read-Host "Enter time to run daily (HH:MM format, e.g., 21:00 for 9 PM)"
if ([string]::IsNullOrWhiteSpace($scheduleTime)) {
    $scheduleTime = "21:00"
}

# Parse time
$timeParts = $scheduleTime.Split(':')
if ($timeParts.Length -ne 2) {
    Write-Host "Invalid time format. Using default: 21:00"
    $timeParts = @("21", "00")
}

$hour = [int]$timeParts[0]
$minute = [int]$timeParts[1]

# Create the scheduled task
$action = New-ScheduledTaskAction -Execute $condaPython -Argument "`"$scriptPath`"" -WorkingDirectory "d:\projects\notion_journal"
$trigger = New-ScheduledTaskTrigger -Daily -At "$($hour.ToString('00')):$($minute.ToString('00'))"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType S4U -RunLevel Highest

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $taskDescription -Force
    Write-Host ""
    Write-Host "✓ Successfully created scheduled task: $taskName" -ForegroundColor Green
    Write-Host "  The task will run daily at $scheduleTime" -ForegroundColor Green
    Write-Host ""
    Write-Host "To modify the schedule, open Task Scheduler and find '$taskName'" -ForegroundColor Yellow
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "✗ Error creating scheduled task: $_" -ForegroundColor Red
    Write-Host "Make sure you're running PowerShell as Administrator" -ForegroundColor Yellow
    Write-Host ""
}
