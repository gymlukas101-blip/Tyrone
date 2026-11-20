// A native Windows Forms test app for the desktop benchmark (compiled on the fly with the .NET Framework csc.exe
// that ships with Windows). Every effect is appended to the log file given as the first argument: the benchmark's
// ground truth. Same controls as win_fixture.ps1, without PowerShell's runspace in the way of UI Automation.
using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

static class WinFixture {
    static string logPath;
    static void L(string s) { File.AppendAllText(logPath, s + Environment.NewLine); }

    [STAThread]
    static void Main(string[] args) {
        logPath = args.Length > 0 ? args[0] : Path.Combine(Path.GetTempPath(), "monkey-fixture.log");
        Application.EnableVisualStyles();
        var f = new Form { Text = "Monkey Fixture", Width = 640, Height = 520, StartPosition = FormStartPosition.Manual,
                           Left = 80, Top = 80 };
        Func<Control, int, int, int, int, Control> add = (c, x, y, w, h) => {
            c.Left = x; c.Top = y; c.Width = w; c.Height = h; f.Controls.Add(c); return c; };

        var name = (TextBox)add(new TextBox { AccessibleName = "Name" }, 20, 20, 200, 28);
        var greet = add(new Button { Text = "Greet" }, 240, 18, 140, 28);
        var outl = (Label)add(new Label { Text = "(nothing yet)" }, 20, 56, 400, 28);
        greet.Click += (s, e) => { outl.Text = "Hello, " + name.Text; L("greet:" + name.Text); };

        var sub = (CheckBox)add(new CheckBox { Text = "Subscribe to updates" }, 20, 90, 200, 28);
        sub.CheckedChanged += (s, e) => L("subscribe:" + (sub.Checked ? "True" : "False"));

        var color = (ComboBox)add(new ComboBox { AccessibleName = "Color", DropDownStyle = ComboBoxStyle.DropDownList },
                                  20, 124, 160, 28);
        color.Items.AddRange(new object[] { "Red", "Green", "Blue" });
        color.SelectedIndex = 0;
        color.SelectedIndexChanged += (s, e) => L("color:" + color.SelectedItem);

        var prepare = add(new Button { Text = "Prepare" }, 20, 160, 140, 28);
        var ready = add(new Button { Text = "Ready", Enabled = false }, 180, 160, 140, 28);
        var timer = new Timer { Interval = 2500 };
        timer.Tick += (s, e) => { timer.Stop(); ready.Enabled = true; };
        prepare.Click += (s, e) => { timer.Start(); L("prepare"); };
        ready.Click += (s, e) => { L("ready"); outl.Text = "Ready pressed"; };

        var rebuild = add(new Button { Text = "Rebuild" }, 20, 196, 140, 28);
        var panel = (Panel)add(new Panel(), 180, 196, 300, 34);
        Action fill = () => {
            panel.Controls.Clear();
            var b = new Button { Text = "Archive", Width = 120 };
            b.Click += (s, e) => { L("archive"); outl.Text = "Archived"; };
            panel.Controls.Add(b);
        };
        fill();
        rebuild.Click += (s, e) => { fill(); L("rebuilt"); };

        var browse = add(new Button { Text = "Browse..." }, 20, 240, 140, 28);
        browse.Click += (s, e) => {
            using (var d = new OpenFileDialog { Title = "Open" }) {
                if (d.ShowDialog(f) == DialogResult.OK) { outl.Text = "Picked " + Path.GetFileName(d.FileName); L("picked:" + d.FileName); }
            }
        };

        var save = add(new Button { Text = "Save settings" }, 180, 240, 140, 28);
        save.Click += (s, e) => { L("saved"); MessageBox.Show(f, "Settings saved.", "Saved"); L("alert_closed"); };

        // Owner-drawn: no accessible children. Only pixels say where "Start" is.
        var paint = (Panel)add(new Panel { AccessibleName = "Paint area" }, 20, 290, 300, 120);
        paint.Paint += (s, e) => {
            e.Graphics.FillRectangle(Brushes.ForestGreen, 100, 35, 100, 50);
            e.Graphics.DrawString("Start", new Font("Segoe UI", 14), Brushes.White, 122, 46);
        };
        paint.MouseClick += (s, e) => {
            if (e.X >= 100 && e.X <= 200 && e.Y >= 35 && e.Y <= 85) { L("canvas_start"); outl.Text = "Started!"; }
        };

        L("launched");
        Application.Run(f);
    }
}
