# Uses pyinstaller to compile exectutable versions of python scripts

$outbase = "./exectuables"

## gui.py
# Compile executable
pyinstaller `
    --onedir `
    --specpath $outbase `
    --distpath "$outbase/dist" `
    --workpath "$outbase/build" `
    --paths ./ `
    --hidden-import numpy `
    --noconsole `
    --clean `
    --noconfirm `
    gui.py

# Add shortcut
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut((Join-Path (Resolve-Path .) "gui.exe.lnk"))
$Shortcut.TargetPath = (Resolve-Path "$outbase/dist/gui/gui.exe")
$Shortcut.Save()
