# Local AI: prints a picture or a text file on a normal (paper) printer — Windows' own printing, no dialog.
# Run by app/paper.py:  powershell -NoProfile -ExecutionPolicy Bypass -File paper_print.ps1 -Kind image -File x.png -Printer "Name" -Copies 1 [-Pdf out.pdf]
# A picture fills the page (kept in proportion, turned to landscape when it's wide); a text flows over as many pages as it needs.
param(
  [Parameter(Mandatory = $true)][ValidateSet("image", "text", "list")][string]$Kind,
  [string]$File = "",
  [string]$Printer = "",
  [int]$Copies = 1,
  [string]$Pdf = ""
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if ($Kind -eq "list") {
  $default = (New-Object System.Drawing.Printing.PrinterSettings).PrinterName
  $names = [System.Drawing.Printing.PrinterSettings]::InstalledPrinters | ForEach-Object { $_ }
  $out = @($names | ForEach-Object { [pscustomobject]@{ name = $_; default = ($_ -eq $default) } })
  ConvertTo-Json -InputObject $out -Compress
  exit 0
}

$doc = New-Object System.Drawing.Printing.PrintDocument
if ($Printer) { $doc.PrinterSettings.PrinterName = $Printer }
if (-not $doc.PrinterSettings.IsValid) { throw "printer not found: $Printer" }
$doc.PrinterSettings.Copies = [Math]::Max(1, [Math]::Min(99, $Copies))
if ($Pdf) { $doc.PrinterSettings.PrintToFile = $true; $doc.PrinterSettings.PrintFileName = $Pdf }  # Microsoft Print to PDF: no "save as"
$doc.DocumentName = [System.IO.Path]::GetFileName($File)

if ($Kind -eq "image") {
  $img = [System.Drawing.Image]::FromFile($File)
  $doc.DefaultPageSettings.Landscape = ($img.Width -gt $img.Height)
  $doc.add_PrintPage({
    param($s, $e)
    $m = $e.MarginBounds
    $k = [Math]::Min($m.Width / $img.Width, $m.Height / $img.Height)
    $w = $img.Width * $k; $h = $img.Height * $k
    $e.Graphics.DrawImage($img, [single]($m.X + ($m.Width - $w) / 2), [single]($m.Y + ($m.Height - $h) / 2), [single]$w, [single]$h)
    $e.HasMorePages = $false
  })
  try { $doc.Print() } finally { $img.Dispose() }
} else {
  $script:rest = [System.IO.File]::ReadAllText($File, [System.Text.Encoding]::UTF8)
  $font = New-Object System.Drawing.Font("Segoe UI", 11)
  $doc.add_PrintPage({
    param($s, $e)
    $fmt = New-Object System.Drawing.StringFormat
    $chars = 0; $lines = 0
    $size = New-Object System.Drawing.SizeF($e.MarginBounds.Width, $e.MarginBounds.Height)
    [void]$e.Graphics.MeasureString($script:rest, $font, $size, $fmt, [ref]$chars, [ref]$lines)
    $e.Graphics.DrawString($script:rest.Substring(0, $chars), $font, [System.Drawing.Brushes]::Black, [System.Drawing.RectangleF]$e.MarginBounds, $fmt)
    $script:rest = $script:rest.Substring($chars)
    $e.HasMorePages = ($script:rest.Length -gt 0)
  })
  try { $doc.Print() } finally { $font.Dispose() }
}
Write-Output "printed"
