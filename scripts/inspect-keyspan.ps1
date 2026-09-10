param([Parameter(Mandatory=$true)][string]$OutputPath)

# Read-only device/driver inventory. No serial handle, installer, or device restart.
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputPath) { throw 'Choose a new evidence file; refusing overwrite.' }
$os = Get-CimInstance Win32_OperatingSystem
$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$devices = @(Get-CimInstance Win32_PnPEntity | Where-Object {
    $_.Name -match 'Keyspan|USA-19|COM7' -or $_.PNPDeviceID -match 'VID_06CD'
})
$drivers = @(Get-CimInstance Win32_PnPSignedDriver | Where-Object {
    $_.DeviceName -match 'Keyspan|USA-19|COM7' -or $_.DeviceID -match 'VID_06CD'
})
$parents = @($devices | ForEach-Object {
    $deviceId = $_.PNPDeviceID
    $parent = Get-PnpDeviceProperty -InstanceId $deviceId -KeyName DEVPKEY_Device_Parent
    [pscustomobject]@{ InstanceId=$deviceId; Parent=$parent.Data }
})
$infMetadata = @($drivers | ForEach-Object {
    $infPath = Join-Path "$env:WINDIR\INF" $_.InfName
    [pscustomobject]@{
        InfName=$_.InfName
        VersionLines=@(Select-String -LiteralPath $infPath -Pattern '^DriverVer','^Provider','^Class=','^Class =','NTamd64' | ForEach-Object { $_.Line })
        SHA256=(Get-FileHash -LiteralPath $infPath -Algorithm SHA256).Hash
    }
})
$result = [ordered]@{
    TimestampUtc=[DateTime]::UtcNow.ToString('o')
    Method='Native Windows CIM/PnP/registry/files; no serial port opened'
    OS=[ordered]@{
        Caption=$os.Caption; Version=$os.Version; BuildNumber=$os.BuildNumber
        Architecture=$os.OSArchitecture; ProcessorArchitecture=$env:PROCESSOR_ARCHITECTURE
        DisplayVersion=$cv.DisplayVersion; UBR=$cv.UBR
    }
    Devices=@($devices | Select-Object Name,PNPDeviceID,HardwareID,Service,Status,ConfigManagerErrorCode)
    Parents=$parents
    Drivers=@($drivers | Select-Object DeviceName,DeviceID,DriverProviderName,DriverVersion,DriverDate,InfName,IsSigned,Signer)
    InstalledInfMetadata=$infMetadata
    PortOccupancy='Not tested: PnP enumeration does not establish whether another application owns a handle'
}
$absoluteOutput = [IO.Path]::GetFullPath($OutputPath)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($absoluteOutput)) | Out-Null
$json = $result | ConvertTo-Json -Depth 8
$stream = [IO.File]::Open($absoluteOutput, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
$writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
try { $writer.WriteLine($json) } finally { $writer.Dispose() }
$json
