param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    Write-Error $Message
    exit 1
}

function Wait-ForHealth {
    param(
        [string]$Uri,
        [int]$MaxAttempts = 20,
        [int]$DelaySeconds = 1
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $result = Invoke-RestMethod -Method Get -Uri $Uri
            if ($result.status -eq "ok") {
                return $result
            }
        }
        catch {
        }

        Start-Sleep -Seconds $DelaySeconds
    }

    Fail "Health endpoint did not become ready after $MaxAttempts attempts: $Uri"
}

try {
    Write-Step "Checking health endpoint"
    $healthUri = "$BaseUrl/health"
    $health = Wait-ForHealth -Uri $healthUri

    Write-Host "Health OK:" ($health | ConvertTo-Json -Depth 10)

    Write-Step "Calling agent run endpoint"
    $runUri = "$BaseUrl/agent/run"
    $body = @{
        conversationId = "ps1-test-1"
        user = "powershell-tester"
        message = "hello from powershell"
        attachments = @()
        metadata = @{
            tenant = "local"
            language = "en"
            extra = @{}
        }
    } | ConvertTo-Json -Depth 10

    $response = Invoke-RestMethod -Method Post -Uri $runUri -ContentType "application/json" -Body $body

    if (-not $response.conversationId -or -not $response.result) {
        Fail "Unexpected /agent/run response: $($response | ConvertTo-Json -Depth 10)"
    }

    Write-Host "Agent run OK:" ($response | ConvertTo-Json -Depth 10)
    exit 0
}
catch {
    Fail "Test failed: $($_.Exception.Message)"
}
