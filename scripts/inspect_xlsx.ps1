param(
  [Parameter(Mandatory = $true)]
  [string]$Path,
  [int]$Rows = 12
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

$zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
try {
  [xml]$sharedXml = Read-ZipText $zip 'xl/sharedStrings.xml'
  $shared = New-Object System.Collections.Generic.List[string]
  foreach ($si in $sharedXml.sst.si) {
    if ($si.t) {
      $shared.Add([string]$si.t)
    } else {
      $shared.Add((($si.r | ForEach-Object { [string]$_.t }) -join ''))
    }
  }

  [xml]$workbookXml = Read-ZipText $zip 'xl/workbook.xml'
  [xml]$relsXml = Read-ZipText $zip 'xl/_rels/workbook.xml.rels'
  $sheetNames = @()
  foreach ($sheet in $workbookXml.workbook.sheets.sheet) {
    $sheetNames += [string]$sheet.name
  }
  Write-Output ("SHEETS: " + ($sheetNames -join ', '))

  [xml]$sheetXml = Read-ZipText $zip 'xl/worksheets/sheet1.xml'

  function Get-CellValue {
    param($Cell)
    $v = [string]$Cell.v
    if ($Cell.t -eq 's') {
      if ($v -ne '') { return $shared[[int]$v] }
      return ''
    }
    if ($Cell.t -eq 'inlineStr') {
      return [string]$Cell.is.t
    }
    return $v
  }

  foreach ($row in $sheetXml.worksheet.sheetData.row | Select-Object -First $Rows) {
    $values = @{}
    foreach ($c in $row.c) {
      $values[(Get-ColIndex $c.r)] = Get-CellValue $c
    }
    $max = 0
    if ($values.Keys.Count -gt 0) {
      $max = ($values.Keys | Measure-Object -Maximum).Maximum
    }
    $arr = for ($i = 1; $i -le $max; $i++) {
      if ($values.ContainsKey($i)) { $values[$i] } else { '' }
    }
    Write-Output ("ROW {0}: {1}" -f $row.r, ($arr -join ' | '))
  }
} finally {
  $zip.Dispose()
}
