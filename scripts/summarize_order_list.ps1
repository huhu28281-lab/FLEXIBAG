param(
  [Parameter(Mandatory = $true)]
  [string]$Path,
  [string]$OutputJson
)

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-ZipText {
  param($Zip, [string]$Name)
  $entry = $Zip.GetEntry($Name)
  if (-not $entry) { return "" }
  $reader = New-Object System.IO.StreamReader($entry.Open())
  try {
    return $reader.ReadToEnd()
  } finally {
    $reader.Dispose()
  }
}

function Get-ColIndex {
  param([string]$Ref)
  $letters = ([regex]::Match($Ref, '^[A-Z]+')).Value
  $n = 0
  foreach ($ch in $letters.ToCharArray()) {
    $n = $n * 26 + ([int][char]$ch - [int][char]'A' + 1)
  }
  return $n
}

function Get-CellValue {
  param($Cell, $Shared)
  $v = [string]$Cell.v
  if ($Cell.t -eq 's') {
    if ($v -ne '') { return $Shared[[int]$v] }
    return ''
  }
  if ($Cell.t -eq 'inlineStr') {
    return [string]$Cell.is.t
  }
  return $v
}

function Get-LocationId {
  param([string]$Carrier, [string]$Port, [string]$Destination)
  $text = (($Carrier, $Port, $Destination) -join ' ').Trim()
  if ($text -match '\uAD70\uC0B0|GUNSAN') { return 'GSN' }
  if ($text -match '\uB300\uC0B0|DAESAN') { return 'DSN' }
  if ($text -match '\uD3C9\uD0DD|PYEONGTAEK') { return 'PTK' }
  if ($text -match '\uC6B8\uC0B0|ULSAN') { return 'ULS' }
  return 'ETC'
}

function Get-LocationName {
  param([string]$LocationId)
  switch ($LocationId) {
    'ULS' { 'ULS' }
    'DSN' { 'DSN' }
    'GSN' { 'GSN' }
    'PTK' { 'PTK' }
    default { 'ETC' }
  }
}

function Get-FlexibagSize {
  param([string]$Serial)
  if ($Serial -match '^22') { return '22KL' }
  if ($Serial -match '^24') { return '24KL' }
  if ($Serial -match '^25') { return '25KL' }
  return 'UNKNOWN'
}

function Normalize-Status {
  param([string]$Status)
  if ($null -eq $Status) { $Status = '' }
  $value = $Status.Trim().ToUpperInvariant()
  if ($value -match 'USED|\uC0AC\uC6A9') { return 'USED' }
  if ($value -match '\uC7AC\uACE0|STOCK|IN') { return 'IN_STOCK' }
  if ($value -match 'DAMAGE|\uD30C\uC190') { return 'DAMAGED' }
  if ($value -match 'LOST|\uBD84\uC2E4') { return 'LOST' }
  if ($value -eq '') { return 'IN_STOCK' }
  return $value
}

$zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
try {
  [xml]$sharedXml = Read-ZipText $zip 'xl/sharedStrings.xml'
  $shared = New-Object System.Collections.Generic.List[string]
  foreach ($si in $sharedXml.sst.si) {
    if ($si.t) { $shared.Add([string]$si.t) }
    else { $shared.Add((($si.r | ForEach-Object { [string]$_.t }) -join '')) }
  }

  [xml]$sheetXml = Read-ZipText $zip 'xl/worksheets/sheet1.xml'
  $rows = $sheetXml.worksheet.sheetData.row
  $data = New-Object System.Collections.Generic.List[object]
  foreach ($row in $rows | Select-Object -Skip 1) {
    $cellMap = @{}
    foreach ($c in $row.c) {
      $cellMap[(Get-ColIndex $c.r)] = Get-CellValue $c $shared
    }

    $serial = [string]$cellMap[4]
    if (-not $serial) { continue }
    $status = Normalize-Status ([string]$cellMap[2])
    $carrier = [string]$cellMap[7]
    $port = [string]$cellMap[6]
    $destination = [string]$cellMap[8]
    $locationId = Get-LocationId $carrier $port $destination

    $data.Add([pscustomobject]@{
      serial_no = $serial.Trim()
      flexibag_size = Get-FlexibagSize $serial
      status = $status
      location_id = $locationId
      location_name = Get-LocationName $locationId
      work_date = [string]$cellMap[1]
      intake_date = [string]$cellMap[3]
      hbl_no = [string]$cellMap[5]
      port = $port
      carrier = $carrier
      destination = $destination
    })
  }

  if ($OutputJson) {
    $data | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
  }

  Write-Output ("TOTAL_ROWS={0}" -f $data.Count)
  Write-Output "STATUS_COUNTS"
  $data | Group-Object status | Sort-Object Name | ForEach-Object { Write-Output ("{0}={1}" -f $_.Name, $_.Count) }
  Write-Output "LOCATION_STATUS_COUNTS"
  $data | Group-Object location_id,status | Sort-Object Name | ForEach-Object { Write-Output ("{0}={1}" -f $_.Name, $_.Count) }
  Write-Output "SIZE_LOCATION_STATUS_COUNTS"
  $data | Group-Object flexibag_size,location_id,status | Sort-Object Name | ForEach-Object { Write-Output ("{0}={1}" -f $_.Name, $_.Count) }
} finally {
  $zip.Dispose()
}
