param([switch]$ReplaceExistingKey)

$ErrorActionPreference = 'Stop'
$deploymentRoot = Split-Path -Parent $PSScriptRoot
$credentials = Get-Content -LiteralPath (Join-Path $deploymentRoot 'secrets/credentials.local.json') -Raw | ConvertFrom-Json
$inventory = Get-Content -LiteralPath (Join-Path $deploymentRoot 'config/deployment.local.json') -Raw | ConvertFrom-Json
$apiKey = ''
foreach ($line in Get-Content -LiteralPath (Join-Path $deploymentRoot 'secrets/model-api.env')) {
    if ($line.StartsWith('QQ_BOT_API_KEY=')) { $apiKey = $line.Substring('QQ_BOT_API_KEY='.Length).Trim() }
}
if (-not $apiKey) { throw 'QQ_BOT_API_KEY is not configured' }

$base = 'http://127.0.0.1:6185'
$phase = 'direct_model_list'
try {
    $direct = Invoke-RestMethod -Uri ($inventory.model_api.base_url.TrimEnd('/') + '/models') -Headers @{Authorization = "Bearer $apiKey"} -TimeoutSec 30
    if (-not $direct.data) { throw 'LiteLLM returned an empty model list' }

    $phase = 'dashboard_login'
    $loginBody = @{username = $credentials.astrbot_username; password = $credentials.astrbot_password} | ConvertTo-Json -Compress
    $login = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" -ContentType 'application/json' -Body $loginBody -TimeoutSec 30
    if (-not $login.data.token) { throw 'Dashboard login did not return a token' }
    $headers = @{Authorization = "Bearer $($login.data.token)"}

    $phase = 'read_source'
    $template = Invoke-RestMethod -Uri "$base/api/config/provider/template" -Headers $headers -TimeoutSec 30
    $source = @($template.data.provider_sources | Where-Object {$_.id -eq 'litellm-lan'})
    if ($source.Count -ne 1) { throw 'Expected exactly one litellm-lan source' }
    $source = $source[0]
    if (-not $ReplaceExistingKey -and ($source.key.Count -ne 1 -or ($source.key[0] -ne '$QQ_BOT_API_KEY' -and $source.key[0] -ne $apiKey))) {
        throw 'The source key was independently changed; refusing to overwrite it'
    }
    $phase = 'update_source'
    $source.key = @($apiKey)
    $body = @{original_id = 'litellm-lan'; config = $source} | ConvertTo-Json -Depth 30 -Compress
    $updated = Invoke-RestMethod -Method Post -Uri "$base/api/config/provider_sources/update" -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 60
    if ($updated.status -ne 'ok') { throw 'Source update failed' }

    $phase = 'dashboard_model_list'
    $modelList = Invoke-RestMethod -Uri "$base/api/config/provider_sources/models?source_id=litellm-lan" -Headers $headers -TimeoutSec 60
    if ($modelList.status -ne 'ok' -or -not $modelList.data.models) { throw 'Dashboard returned no models' }
    $phase = 'chat_provider_check'
    $chatCheck = Invoke-RestMethod -Uri "$base/api/config/provider/check_one?id=litellm-default-chat" -Headers $headers -TimeoutSec 150
    if ($chatCheck.status -ne 'ok' -or $chatCheck.data.status -ne 'available') { throw 'The chat provider check failed' }
    $result = [ordered]@{
        verified_at = (Get-Date).ToString('o')
        direct_model_count = @($direct.data).Count
        dashboard_model_count = @($modelList.data.models).Count
        model_list_status = $modelList.status
        chat_check = $chatCheck
        reason = 'Dashboard model-list provider does not expand environment variable keys'
        fix = 'Store the resolved API key in the native provider source using the authenticated dashboard API'
    }
    $result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $deploymentRoot 'logs/model-list-verification.json') -Encoding utf8
    $result | ConvertTo-Json -Depth 10
} catch {
    # HTTP errors can echo credentials. Return only the phase and HTTP status.
    $httpStatus = $null
    if ($_.Exception.Response) { $httpStatus = [int]$_.Exception.Response.StatusCode }
    @{ok = $false; phase = $phase; http_status = $httpStatus; error_type = $_.Exception.GetType().Name} | ConvertTo-Json -Compress
    exit 1
}
