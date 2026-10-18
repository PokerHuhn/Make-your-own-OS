@echo off
echo [1/3] Kompiliere main.lwkossl...
python compiler.py main.lwkossl

if errorlevel 1 (
    echo [FEHLER]: Kompilierung fehlgeschlagen!
    pause
    exit /b
)

echo [2/3] Starte QEMU...
qemu-system-x86_64 -drive format=raw,file=os.bin

echo [3/3] QEMU beendet.
