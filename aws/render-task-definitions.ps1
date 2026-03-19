[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Region,

    [string]$AccountId,
    [string]$RepositoryName = "docintel",
    [string]$ImageTag = "latest",
    [string]$ImageUri,
    [string]$ExecutionRoleArn,
    [string]$TaskRoleArn,
    [string]$ExecutionRoleName = "ecsTaskExecutionRole",
    [string]$TaskRoleName = "ecsTaskRole",
    [string]$UploadsBucket,
    [string]$ExportsBucket,
    [string]$DatabaseUrlSecretArn,
    [string]$CeleryBrokerSecretArn,
    [string]$CeleryResultBackendSecretArn,
    [string]$ApiKeysSecretArn,
    [string]$WebhookSecretArn,
    [string]$AnthropicApiKeySecretArn,
    [string]$EmailAddressSecretArn,
    [string]$EmailPasswordSecretArn,
    [string]$DatabaseUrlSecretName = "docintel/database-url",
    [string]$CeleryBrokerSecretName = "docintel/redis-broker",
    [string]$CeleryResultBackendSecretName = "docintel/redis-backend",
    [string]$ApiKeysSecretName = "docintel/api-keys",
    [string]$WebhookSecretName = "docintel/webhook-secret",
    [string]$AnthropicApiKeySecretName = "docintel/anthropic-api-key",
    [string]$EmailAddressSecretName = "docintel/email-address",
    [string]$EmailPasswordSecretName = "docintel/email-password",
    [string]$OutputDirectory = "",
    [switch]$IncludeReviewUi,
    [switch]$SkipOptionalSecretLookup,
    [string]$ReviewApiBase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-AwsText {
    param([string[]]$Arguments)

    $output = & aws @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "aws $($Arguments -join ' ') failed.`n$output"
    }
    return ($output | Out-String).Trim()
}

function Resolve-AccountId {
    if ($AccountId) {
        return $AccountId
    }
    return Invoke-AwsText @("sts", "get-caller-identity", "--query", "Account", "--output", "text", "--region", $Region)
}

function Resolve-RoleArn {
    param(
        [string]$Arn,
        [string]$RoleName
    )

    if ($Arn) {
        return $Arn
    }
    return Invoke-AwsText @("iam", "get-role", "--role-name", $RoleName, "--query", "Role.Arn", "--output", "text")
}

function Resolve-SecretArn {
    param(
        [string]$Arn,
        [string]$SecretName,
        [bool]$Optional = $false
    )

    if ($Arn) {
        return $Arn
    }

    $output = & aws secretsmanager describe-secret --secret-id $SecretName --region $Region --query ARN --output text 2>&1
    if ($LASTEXITCODE -eq 0) {
        return ($output | Out-String).Trim()
    }
    if ($Optional) {
        Write-Verbose "Skipping optional secret '$SecretName' because it was not found."
        return $null
    }
    throw "Required secret '$SecretName' could not be resolved.`n$output"
}

function Set-EnvironmentValue {
    param(
        [object[]]$Environment,
        [string]$Name,
        [string]$Value
    )

    foreach ($item in $Environment) {
        if ($item.name -eq $Name) {
            $item.value = $Value
            return
        }
    }
    throw "Environment variable '$Name' not found in template."
}

function Set-SecretValue {
    param(
        [object[]]$Secrets,
        [string]$Name,
        [string]$Value,
        [bool]$Optional = $false
    )

    $filtered = @()
    $matched = $false
    foreach ($item in $Secrets) {
        if ($item.name -eq $Name) {
            $matched = $true
            if ($Value) {
                $item.valueFrom = $Value
                $filtered += $item
            }
            elseif (-not $Optional) {
                throw "Required secret '$Name' is missing."
            }
        }
        else {
            $filtered += $item
        }
    }

    if (-not $matched -and -not $Optional) {
        throw "Secret '$Name' not found in template."
    }
    return $filtered
}

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot "rendered"
}

$resolvedAccountId = Resolve-AccountId
if (-not $ImageUri) {
    $ImageUri = "$resolvedAccountId.dkr.ecr.$Region.amazonaws.com/${RepositoryName}:$ImageTag"
}
if (-not $UploadsBucket) {
    $UploadsBucket = "docintel-uploads-$resolvedAccountId"
}
if (-not $ExportsBucket) {
    $ExportsBucket = "docintel-exports-$resolvedAccountId"
}

$resolvedExecutionRoleArn = Resolve-RoleArn -Arn $ExecutionRoleArn -RoleName $ExecutionRoleName
$resolvedTaskRoleArn = Resolve-RoleArn -Arn $TaskRoleArn -RoleName $TaskRoleName

$secretArns = @{
    DATABASE_URL = Resolve-SecretArn -Arn $DatabaseUrlSecretArn -SecretName $DatabaseUrlSecretName
    CELERY_BROKER_URL = Resolve-SecretArn -Arn $CeleryBrokerSecretArn -SecretName $CeleryBrokerSecretName
    CELERY_RESULT_BACKEND = Resolve-SecretArn -Arn $CeleryResultBackendSecretArn -SecretName $CeleryResultBackendSecretName
    API_KEYS = Resolve-SecretArn -Arn $ApiKeysSecretArn -SecretName $ApiKeysSecretName
    WEBHOOK_SECRET = Resolve-SecretArn -Arn $WebhookSecretArn -SecretName $WebhookSecretName
    ANTHROPIC_API_KEY = if ($SkipOptionalSecretLookup -and -not $AnthropicApiKeySecretArn) { $null } else { Resolve-SecretArn -Arn $AnthropicApiKeySecretArn -SecretName $AnthropicApiKeySecretName -Optional $true }
    EMAIL_ADDRESS = if ($SkipOptionalSecretLookup -and -not $EmailAddressSecretArn) { $null } else { Resolve-SecretArn -Arn $EmailAddressSecretArn -SecretName $EmailAddressSecretName -Optional $true }
    EMAIL_PASSWORD = if ($SkipOptionalSecretLookup -and -not $EmailPasswordSecretArn) { $null } else { Resolve-SecretArn -Arn $EmailPasswordSecretArn -SecretName $EmailPasswordSecretName -Optional $true }
}

$templateFiles = @(
    "ecs-task-definition-api-fargate.json",
    "ecs-task-definition-worker-fargate.json",
    "ecs-task-definition-worker-high-fargate.json",
    "ecs-task-definition-worker-webhooks-fargate.json"
)

if ($IncludeReviewUi) {
    if (-not $ReviewApiBase) {
        throw "Review UI deployment requires -ReviewApiBase, for example https://your-alb-dns/api/v1"
    }
    $templateFiles += "ecs-task-definition-review-ui-fargate.json"
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$renderedFiles = @()
foreach ($fileName in $templateFiles) {
    $templatePath = Join-Path $PSScriptRoot $fileName
    $outputPath = Join-Path $OutputDirectory $fileName

    $taskDefinition = Get-Content -Raw -Path $templatePath | ConvertFrom-Json
    $taskDefinition.executionRoleArn = $resolvedExecutionRoleArn
    $taskDefinition.taskRoleArn = $resolvedTaskRoleArn

    $container = $taskDefinition.containerDefinitions[0]
    $container.image = $ImageUri

    Set-EnvironmentValue -Environment $container.environment -Name "S3_REGION" -Value $Region
    Set-EnvironmentValue -Environment $container.environment -Name "S3_BUCKET_UPLOADS" -Value $UploadsBucket
    Set-EnvironmentValue -Environment $container.environment -Name "S3_BUCKET_EXPORTS" -Value $ExportsBucket
    if ($container.name -eq "review-ui") {
        Set-EnvironmentValue -Environment $container.environment -Name "REVIEW_API_BASE" -Value $ReviewApiBase
    }

    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "DATABASE_URL" -Value $secretArns.DATABASE_URL
    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "CELERY_BROKER_URL" -Value $secretArns.CELERY_BROKER_URL
    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "CELERY_RESULT_BACKEND" -Value $secretArns.CELERY_RESULT_BACKEND
    if ($container.name -eq "api") {
        $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "API_KEYS" -Value $secretArns.API_KEYS
        $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "WEBHOOK_SECRET" -Value $secretArns.WEBHOOK_SECRET
    }
    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "ANTHROPIC_API_KEY" -Value $secretArns.ANTHROPIC_API_KEY -Optional $true
    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "EMAIL_ADDRESS" -Value $secretArns.EMAIL_ADDRESS -Optional $true
    $container.secrets = Set-SecretValue -Secrets $container.secrets -Name "EMAIL_PASSWORD" -Value $secretArns.EMAIL_PASSWORD -Optional $true

    if ($container.logConfiguration.options."awslogs-region") {
        $container.logConfiguration.options."awslogs-region" = $Region
    }

    $taskDefinition | ConvertTo-Json -Depth 20 | Set-Content -Path $outputPath
    $renderedFiles += $outputPath
}

$renderedFiles | ForEach-Object { Write-Output $_ }
