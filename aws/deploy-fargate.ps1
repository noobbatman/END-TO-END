[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Region,

    [string]$AccountId,
    [string]$RepositoryName = "docintel",
    [string]$ImageTag = "",
    [string]$ClusterName = "docintel",
    [string]$ApiServiceName = "docintel-api",
    [string]$WorkerServiceName = "docintel-worker",
    [string]$WorkerHighServiceName = "docintel-worker-high",
    [string]$WorkerWebhooksServiceName = "docintel-worker-webhooks",
    [string]$ReviewUiServiceName = "docintel-review-ui",
    [string[]]$PrivateSubnets,
    [string]$ApiSecurityGroup,
    [string]$WorkerSecurityGroup,
    [string]$ReviewUiSecurityGroup,
    [string]$ApiTargetGroupArn,
    [string]$ReviewUiTargetGroupArn,
    [switch]$EnsureCluster,
    [switch]$CreateServices,
    [switch]$UpdateServices,
    [switch]$WaitForStability,
    [switch]$RunMigrations,
    [switch]$IncludeReviewUi,
    [string]$ReviewApiBase,
    [int]$ApiDesiredCount = 1,
    [int]$WorkerDesiredCount = 1,
    [int]$WorkerHighDesiredCount = 1,
    [int]$WorkerWebhooksDesiredCount = 1,
    [int]$ReviewUiDesiredCount = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-External {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    Write-Host "> $Executable $($Arguments -join ' ')"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE."
    }
}

function Invoke-AwsText {
    param([string[]]$Arguments)

    $output = & aws @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "aws $($Arguments -join ' ') failed.`n$output"
    }
    return ($output | Out-String).Trim()
}

function Test-ClusterExists {
    param([string]$Name)

    $status = Invoke-AwsText @("ecs", "describe-clusters", "--clusters", $Name, "--region", $Region, "--query", "clusters[0].status", "--output", "text")
    return $status -eq "ACTIVE"
}

function Test-ServiceExists {
    param(
        [string]$Cluster,
        [string]$ServiceName
    )

    $response = & aws ecs describe-services --cluster $Cluster --services $ServiceName --region $Region --query services[0].status --output text 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    $status = ($response | Out-String).Trim()
    return $status -and $status -ne "None" -and $status -ne "INACTIVE"
}

function Ensure-ClusterExists {
    param([string]$Name)

    if (Test-ClusterExists -Name $Name) {
        return
    }
    Invoke-External -Executable "aws" -Arguments @("ecs", "create-cluster", "--cluster-name", $Name, "--capacity-providers", "FARGATE", "--region", $Region)
}

function Ensure-LogGroup {
    param([string]$LogGroupName)

    $exists = Invoke-AwsText @("logs", "describe-log-groups", "--log-group-name-prefix", $LogGroupName, "--region", $Region, "--query", "length(logGroups[?logGroupName=='$LogGroupName'])", "--output", "text")
    if ($exists -eq "0") {
        Invoke-External -Executable "aws" -Arguments @("logs", "create-log-group", "--log-group-name", $LogGroupName, "--region", $Region)
    }
    Invoke-External -Executable "aws" -Arguments @("logs", "put-retention-policy", "--log-group-name", $LogGroupName, "--retention-in-days", "7", "--region", $Region)
}

function New-NetworkConfiguration {
    param(
        [string[]]$Subnets,
        [string]$SecurityGroup
    )

    $subnetsText = ($Subnets -join ",")
    return "awsvpcConfiguration={subnets=[$subnetsText],securityGroups=[$SecurityGroup],assignPublicIp=DISABLED}"
}

function Ensure-Service {
    param(
        [string]$ServiceName,
        [string]$TaskDefinition,
        [string]$NetworkConfiguration,
        [int]$DesiredCount,
        [string]$SecurityTagValue,
        [string]$TargetGroupArn = "",
        [string]$ContainerName = "",
        [string]$ContainerPort = ""
    )

    if (Test-ServiceExists -Cluster $ClusterName -ServiceName $ServiceName) {
        Invoke-External -Executable "aws" -Arguments @(
            "ecs", "update-service",
            "--cluster", $ClusterName,
            "--service", $ServiceName,
            "--task-definition", $TaskDefinition,
            "--desired-count", $DesiredCount,
            "--force-new-deployment",
            "--region", $Region
        )
        return
    }

    $arguments = @(
        "ecs", "create-service",
        "--cluster", $ClusterName,
        "--service-name", $ServiceName,
        "--task-definition", $TaskDefinition,
        "--desired-count", $DesiredCount,
        "--launch-type", "FARGATE",
        "--enable-execute-command",
        "--network-configuration", $NetworkConfiguration,
        "--region", $Region,
        "--tags", "key=Environment,value=production", "key=Service,value=$SecurityTagValue"
    )

    if ($TargetGroupArn) {
        $arguments += @("--load-balancers", "targetGroupArn=$TargetGroupArn,containerName=$ContainerName,containerPort=$ContainerPort")
    }

    Invoke-External -Executable "aws" -Arguments $arguments
}

if (-not $ImageTag) {
    $ImageTag = Get-Date -Format "yyyyMMdd-HHmmss"
}
if (-not $AccountId) {
    $AccountId = Invoke-AwsText @("sts", "get-caller-identity", "--query", "Account", "--output", "text", "--region", $Region)
}

$imageUri = "$AccountId.dkr.ecr.$Region.amazonaws.com/${RepositoryName}:$ImageTag"

Invoke-External -Executable "aws" -Arguments @("ecr", "describe-repositories", "--repository-names", $RepositoryName, "--region", $Region)
$password = Invoke-AwsText @("ecr", "get-login-password", "--region", $Region)
$password | docker login --username AWS --password-stdin "$AccountId.dkr.ecr.$Region.amazonaws.com"
if ($LASTEXITCODE -ne 0) {
    throw "docker login failed."
}

Invoke-External -Executable "docker" -Arguments @("build", "-t", "$RepositoryName`:$ImageTag", ".")
Invoke-External -Executable "docker" -Arguments @("tag", "$RepositoryName`:$ImageTag", $imageUri)
Invoke-External -Executable "docker" -Arguments @("tag", "$RepositoryName`:$ImageTag", "$AccountId.dkr.ecr.$Region.amazonaws.com/$RepositoryName:latest")
Invoke-External -Executable "docker" -Arguments @("push", $imageUri)
Invoke-External -Executable "docker" -Arguments @("push", "$AccountId.dkr.ecr.$Region.amazonaws.com/$RepositoryName:latest")

$renderArguments = @(
    "-File", (Join-Path $PSScriptRoot "render-task-definitions.ps1"),
    "-Region", $Region,
    "-AccountId", $AccountId,
    "-RepositoryName", $RepositoryName,
    "-ImageTag", $ImageTag
)
if ($IncludeReviewUi) {
    $renderArguments += @("-IncludeReviewUi")
    if (-not $ReviewApiBase) {
        throw "Review UI deployment requires -ReviewApiBase."
    }
    $renderArguments += @("-ReviewApiBase", $ReviewApiBase)
}

$renderedFiles = & powershell @renderArguments
if ($LASTEXITCODE -ne 0) {
    throw "Task definition rendering failed."
}

foreach ($renderedFile in $renderedFiles) {
    Invoke-External -Executable "aws" -Arguments @("ecs", "register-task-definition", "--cli-input-json", "file://$renderedFile", "--region", $Region)
}

if ($EnsureCluster) {
    Ensure-ClusterExists -Name $ClusterName
}

if ($CreateServices -or $UpdateServices) {
    if (-not $PrivateSubnets -or -not $ApiSecurityGroup -or -not $WorkerSecurityGroup) {
        throw "Service creation/update requires -PrivateSubnets, -ApiSecurityGroup, and -WorkerSecurityGroup."
    }
    if (-not $ApiTargetGroupArn) {
        throw "API deployment requires -ApiTargetGroupArn."
    }

    Ensure-LogGroup -LogGroupName "/ecs/docintel-api"
    Ensure-LogGroup -LogGroupName "/ecs/docintel-worker"
    Ensure-LogGroup -LogGroupName "/ecs/docintel-worker-high"
    Ensure-LogGroup -LogGroupName "/ecs/docintel-worker-webhooks"
    if ($IncludeReviewUi) {
        Ensure-LogGroup -LogGroupName "/ecs/docintel-review-ui"
    }

    $apiNetwork = New-NetworkConfiguration -Subnets $PrivateSubnets -SecurityGroup $ApiSecurityGroup
    $workerNetwork = New-NetworkConfiguration -Subnets $PrivateSubnets -SecurityGroup $WorkerSecurityGroup

    Ensure-Service -ServiceName $ApiServiceName -TaskDefinition "docintel-api" -NetworkConfiguration $apiNetwork -DesiredCount $ApiDesiredCount -SecurityTagValue "api" -TargetGroupArn $ApiTargetGroupArn -ContainerName "api" -ContainerPort "8000"
    Ensure-Service -ServiceName $WorkerServiceName -TaskDefinition "docintel-worker" -NetworkConfiguration $workerNetwork -DesiredCount $WorkerDesiredCount -SecurityTagValue "worker-normal"
    Ensure-Service -ServiceName $WorkerHighServiceName -TaskDefinition "docintel-worker-high" -NetworkConfiguration $workerNetwork -DesiredCount $WorkerHighDesiredCount -SecurityTagValue "worker-high"
    Ensure-Service -ServiceName $WorkerWebhooksServiceName -TaskDefinition "docintel-worker-webhooks" -NetworkConfiguration $workerNetwork -DesiredCount $WorkerWebhooksDesiredCount -SecurityTagValue "worker-webhooks"

    if ($IncludeReviewUi) {
        if (-not $ReviewUiTargetGroupArn) {
            throw "Review UI deployment requires -ReviewUiTargetGroupArn."
        }
        if (-not $ReviewUiSecurityGroup) {
            $ReviewUiSecurityGroup = $ApiSecurityGroup
        }
        $reviewNetwork = New-NetworkConfiguration -Subnets $PrivateSubnets -SecurityGroup $ReviewUiSecurityGroup
        Ensure-Service -ServiceName $ReviewUiServiceName -TaskDefinition "docintel-review-ui" -NetworkConfiguration $reviewNetwork -DesiredCount $ReviewUiDesiredCount -SecurityTagValue "review-ui" -TargetGroupArn $ReviewUiTargetGroupArn -ContainerName "review-ui" -ContainerPort "8501"
    }
}

if ($WaitForStability -and ($CreateServices -or $UpdateServices)) {
    $servicesToWaitFor = @($ApiServiceName, $WorkerServiceName, $WorkerHighServiceName, $WorkerWebhooksServiceName)
    if ($IncludeReviewUi) {
        $servicesToWaitFor += $ReviewUiServiceName
    }
    foreach ($serviceName in $servicesToWaitFor) {
        Invoke-External -Executable "aws" -Arguments @("ecs", "wait", "services-stable", "--cluster", $ClusterName, "--services", $serviceName, "--region", $Region)
    }
}

if ($RunMigrations) {
    if (-not $PrivateSubnets -or -not $ApiSecurityGroup) {
        throw "Running migrations requires -PrivateSubnets and -ApiSecurityGroup."
    }
    $networkConfiguration = New-NetworkConfiguration -Subnets $PrivateSubnets -SecurityGroup $ApiSecurityGroup
    $overrideJson = '{"containerOverrides":[{"name":"api","command":["alembic","upgrade","head"]}]}'
    $taskArn = Invoke-AwsText @(
        "ecs", "run-task",
        "--cluster", $ClusterName,
        "--task-definition", "docintel-api",
        "--launch-type", "FARGATE",
        "--network-configuration", $networkConfiguration,
        "--overrides", $overrideJson,
        "--region", $Region,
        "--query", "tasks[0].taskArn",
        "--output", "text"
    )
    Invoke-External -Executable "aws" -Arguments @("ecs", "wait", "tasks-stopped", "--cluster", $ClusterName, "--tasks", $taskArn, "--region", $Region)
    $exitCode = Invoke-AwsText @("ecs", "describe-tasks", "--cluster", $ClusterName, "--tasks", $taskArn, "--region", $Region, "--query", "tasks[0].containers[0].exitCode", "--output", "text")
    if ($exitCode -ne "0") {
        throw "Migration task failed with exit code $exitCode."
    }
}

Write-Host ""
Write-Host "Deployment artifacts registered successfully."
Write-Host "Image URI: $imageUri"
