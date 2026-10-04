// "Local AI.exe" — starts Local AI from its own folder, wherever that folder is (another drive, another PC).
// Every start it points the Python environments (.venv and every engines\<name>\venv: Laya, the sound-effects
// engine...) at the Python bundled in engines\python — a venv remembers its Python's full path, which breaks when
// the folder moves — then runs LocalAI.pyw without a console window. "/fix" = only repair the paths (used by Setup).
// Build: tools\launcher\build.cmd (the C# compiler that comes with Windows; works on any Windows 10/11).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string pyHome = Path.Combine(root, @"engines\python");
        bool fixOnly = args.Any(a => a.Equals("/fix", StringComparison.OrdinalIgnoreCase));
        var problems = new List<string>();
        if (File.Exists(Path.Combine(pyHome, "python.exe")))
        {
            var cfgs = new List<string> { @".venv\pyvenv.cfg" };
            string engines = Path.Combine(root, "engines");
            if (Directory.Exists(engines))  // engines\laya\venv, engines\woosh\venv, ... (the sound engine was missed once)
                foreach (var d in Directory.GetDirectories(engines))
                    cfgs.Add(Path.Combine("engines", Path.GetFileName(d), @"venv\pyvenv.cfg"));
            foreach (var cfg in cfgs)
            {
                string f = Path.Combine(root, cfg);
                if (!File.Exists(f)) continue;
                try
                {
                    var lines = File.ReadAllLines(f);
                    bool changed = false;
                    for (int i = 0; i < lines.Length; i++)
                        if (lines[i].TrimStart().StartsWith("home", StringComparison.OrdinalIgnoreCase)
                            && lines[i].Trim() != "home = " + pyHome)
                        {
                            lines[i] = "home = " + pyHome;
                            changed = true;
                        }
                    if (changed) File.WriteAllLines(f, lines);
                }
                catch (Exception e) { problems.Add(cfg + ": " + e.Message); }
            }
        }
        else problems.Add(@"engines\python (the bundled Python) is missing");
        if (fixOnly)
        {
            foreach (var p in problems) Console.Error.WriteLine(p);
            return problems.Count == 0 ? 0 : 1;
        }
        string pyw = Path.Combine(root, @".venv\Scripts\pythonw.exe"), app = Path.Combine(root, "LocalAI.pyw");
        if (!File.Exists(pyw)) problems.Add(@".venv (the app's Python packages) is missing");
        if (!File.Exists(app)) problems.Add("LocalAI.pyw is missing");
        if (problems.Count > 0 && (!File.Exists(pyw) || !File.Exists(app) || !File.Exists(Path.Combine(pyHome, "python.exe"))))
        {
            MessageBox.Show("Local AI can't start — parts are missing in\n" + root + "\n\n- " + string.Join("\n- ", problems)
                + "\n\nCopy the WHOLE Local AI folder again (with .venv, engines and models), or run install.ps1.",
                "Local AI", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        Process.Start(new ProcessStartInfo(pyw, "\"" + app + "\"") { WorkingDirectory = root, UseShellExecute = false });
        return 0;
    }
}
