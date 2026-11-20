# A native Windows Forms test app for the desktop benchmark. Every user-visible effect is also appended to the log
# file given as the first argument, which is the ground truth the benchmark scores against.
#   powershell -NoProfile -ExecutionPolicy Bypass -File win_fixture.ps1 C:\path\fixture.log
param([string]$Log = "$env:TEMP\monkey-fixture.log")
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
function L([string]$s) { Add-Content -Path $Log -Value $s -Encoding UTF8 }

$f = New-Object System.Windows.Forms.Form
$f.Text = "Monkey Fixture"; $f.Width = 640; $f.Height = 520; $f.StartPosition = "Manual"; $f.Left = 80; $f.Top = 80

function Add($c, $x, $y, $w = 140, $h = 28) { $c.Left = $x; $c.Top = $y; $c.Width = $w; $c.Height = $h; $f.Controls.Add($c); $c }

$name = Add (New-Object System.Windows.Forms.TextBox) 20 20 200; $name.AccessibleName = "Name"
$greet = Add (New-Object System.Windows.Forms.Button) 240 18; $greet.Text = "Greet"
$out = Add (New-Object System.Windows.Forms.Label) 20 56 400; $out.Text = "(nothing yet)"
$greet.Add_Click({ $out.Text = "Hello, " + $name.Text; L ("greet:" + $name.Text) })

$sub = Add (New-Object System.Windows.Forms.CheckBox) 20 90 200; $sub.Text = "Remember my choice"
$sub.Add_CheckedChanged({ L ("remember:" + $sub.Checked) })

$color = Add (New-Object System.Windows.Forms.ComboBox) 20 124 160; $color.AccessibleName = "Color"
$color.DropDownStyle = "DropDownList"; [void]$color.Items.AddRange(@("Red", "Green", "Blue")); $color.SelectedIndex = 0
$color.Add_SelectedIndexChanged({ L ("color:" + $color.SelectedItem) })

$slow = Add (New-Object System.Windows.Forms.Button) 20 160; $slow.Text = "Prepare"
$ready = Add (New-Object System.Windows.Forms.Button) 180 160; $ready.Text = "Ready"; $ready.Enabled = $false
$timer = New-Object System.Windows.Forms.Timer; $timer.Interval = 2500
$timer.Add_Tick({ $timer.Stop(); $ready.Enabled = $true })
$slow.Add_Click({ $timer.Start(); L "prepare" })
$ready.Add_Click({ L "ready"; $out.Text = "Ready pressed" })

$rebuild = Add (New-Object System.Windows.Forms.Button) 20 196; $rebuild.Text = "Rebuild"
$panel = Add (New-Object System.Windows.Forms.Panel) 180 196 300 34
function Fill() {
  $panel.Controls.Clear()
  $b = New-Object System.Windows.Forms.Button; $b.Text = "Archive"; $b.Width = 120; $panel.Controls.Add($b)
  $b.Add_Click({ L "archive"; $out.Text = "Archived" })
}
Fill
$rebuild.Add_Click({ Fill; L "rebuilt" })

$browse = Add (New-Object System.Windows.Forms.Button) 20 240; $browse.Text = "Browse..."
$browse.Add_Click({
  $d = New-Object System.Windows.Forms.OpenFileDialog; $d.Title = "Open"
  if ($d.ShowDialog($f) -eq "OK") { $out.Text = "Picked " + [IO.Path]::GetFileName($d.FileName); L ("picked:" + $d.FileName) }
})

$alert = Add (New-Object System.Windows.Forms.Button) 180 240; $alert.Text = "Save settings"
$alert.Add_Click({ L "saved"; [void][System.Windows.Forms.MessageBox]::Show($f, "Settings saved.", "Saved") ; L "alert_closed" })

# Owner-drawn area: no accessible children. Only pixels say where "Start" is.
$paint = Add (New-Object System.Windows.Forms.Panel) 20 290 300 120; $paint.AccessibleName = "Paint area"
$paint.Add_Paint({ param($s, $e)
  $e.Graphics.FillRectangle([System.Drawing.Brushes]::ForestGreen, 100, 35, 100, 50)
  $e.Graphics.DrawString("Start", (New-Object System.Drawing.Font "Segoe UI", 14), [System.Drawing.Brushes]::White, 122, 46) })
$paint.Add_MouseClick({ param($s, $e)
  if ($e.X -ge 100 -and $e.X -le 200 -and $e.Y -ge 35 -and $e.Y -le 85) { L "canvas_start"; $out.Text = "Started!" } })

L "launched"
[System.Windows.Forms.Application]::Run($f)
