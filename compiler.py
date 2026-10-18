# -*- coding: utf-8 -*-
import sys
import re
import os
from PIL import Image

def rgb_to_vga(r, g, b):
    """Konvertiert RGB-Werte in den Standard VGA 256-Farben-Modus (Modus 13h Farbdschungel / 6x6x6 Würfel)."""
    if r < 40 and g < 40 and b < 40:
        return 0  # Schwarz / Transparent-Ersatz
    if r == g == b:
        if r < 8: return 0
        if r > 248: return 15
        return 232 + int((r - 8) / (248 - 8) * 23)
    
    ri = min(5, max(0, (r + 25) // 51))
    gi = min(5, max(0, (g + 25) // 51))
    bi = min(5, max(0, (b + 25) // 51))
    return 16 + (36 * ri) + (6 * gi) + bi

class QemuOSCompiler:
    def __init__(self):
        self.code = bytearray()
        self.cursor_image_path = None

    def compile_line(self, line):
        line = line.strip()
        if not line or line.startswith("//"):
            return

        # Befehl: Grafikmodus umschalten (VGA 320x200, 256 Farben, Modus 13h)
        if line == "set graphics mode":
            self.code.extend(b'\xB8\x13\x00')  # mov ax, 0x0013
            self.code.extend(b'\xCD\x10')      # int 0x10

        # Befehl: Bildschirm mit Farbe fluten
        elif line.startswith("clear screen with color "):
            try:
                color = int(line.replace("clear screen with color ", "").strip())
            except ValueError:
                color = 0
            
            self.code.extend(b'\xB8\x00\xA0')  # mov ax, 0xA000
            self.code.extend(b'\x8E\xC0')      # mov es, ax
            self.code.extend(b'\x31\xFF')      # xor di, di
            self.code.extend(b'\xB0' + bytes([color & 0xFF]))
            self.code.extend(b'\xB9\x00\xFA')  # mov cx, 64000
            self.code.extend(b'\xF3\xAA')      # rep stosb

        # Befehl: Fenster/Rechteck zeichnen
        elif line.startswith("draw window at "):
            match = re.match(r'draw window at\s+(\d+),\s*(\d+)\s+with size\s+(\d+),\s*(\d+)\s+color\s+(\d+)', line)
            if match:
                x = int(match.group(1))
                y = int(match.group(2))
                w = int(match.group(3))
                h = int(match.group(4))
                color = int(match.group(5))

                for row in range(h):
                    curr_y = y + row
                    if curr_y >= 200:
                        break
                    start_offset = curr_y * 320 + x
                    if start_offset > 65535:
                        break

                    self.code.extend(b'\xB8\x00\xA0')
                    self.code.extend(b'\x8E\xC0')
                    self.code.extend(b'\xBF' + start_offset.to_bytes(2, 'little'))
                    self.code.extend(b'\xB9' + w.to_bytes(2, 'little'))
                    self.code.extend(b'\xB0' + bytes([color & 0xFF]))
                    self.code.extend(b'\xF3\xAA')

        # Befehl: Benutzerdefinierten Cursor aus PNG/ICO festlegen
        elif line.startswith("cursor-ico("):
            match = re.match(r'cursor-ico\s*\(\s*["\'](.+?)["\']\s*\)', line)
            if match:
                self.cursor_image_path = match.group(1)

        # Befehl: Robuster PS/2-Maus-Treiber
        elif line == "enable mouse":
            self.code.extend(b'\xFA')                      # cli
            self.code.extend(b'\xE4\x64\xB0\xA8\xE6\x64')  # Aux port aktivieren
            self.code.extend(b'\xE4\x64\xB0\xD4\xE6\x64')  # Write mouse command
            self.code.extend(b'\xB0\xF4\xE6\x60')         # Enable data reporting
            
            if self.cursor_image_path and os.path.exists(self.cursor_image_path):
                img = Image.open(self.cursor_image_path).convert("RGBA")
                if img.width > 32 or img.height > 32:
                    img = img.resize((32, 32), Image.Resampling.NEAREST)
                
                img_w, img_h = img.size
                pixels = img.load()
                
                # Startposition: X = 160, Y = 100
                self.code.extend(b'\xBF\xA0\x00')          # mov di, 160 (X)
                self.code.extend(b'\xBD\x64\x00')          # mov bp, 100 (Y)
                
                self.code.extend(b'\xB8\x00\xA0')          # mov ax, 0xA000
                self.code.extend(b'\x8E\xC0')              # mov es, ax
                self.code.extend(b'\x0E\x1F')              # push cs; pop ds

                # 1. Hintergrund für alle Bild-Pixel sichern
                for py in range(img_h):
                    for px in range(img_w):
                        r, g, b, a = pixels[px, py]
                        if a > 30:
                            offset_expr = py * 320 + px
                            self.code.extend(b'\x89\xE8')                  # mov ax, bp
                            self.code.extend(b'\xB9\x40\x01')              # mov cx, 320
                            self.code.extend(b'\xF7\xE1')                  # mul cx
                            self.code.extend(b'\x01\xF8')                  # add ax, di
                            if offset_expr > 0:
                                self.code.extend(b'\x05' + offset_expr.to_bytes(2, 'little'))
                            self.code.extend(b'\x89\xC6')                  # mov si, ax
                            self.code.extend(b'\x26\x8A\x04')              # mov al, byte ptr es:[si]
                            self.code.extend(b'\x50')                      # push ax

                # 2. Bild-Pixel zeichnen
                for py in range(img_h):
                    for px in range(img_w):
                        r, g, b, a = pixels[px, py]
                        if a > 30:
                            vga_col = rgb_to_vga(r, g, b)
                            offset_expr = py * 320 + px
                            self.code.extend(b'\x89\xE8')                  # mov ax, bp
                            self.code.extend(b'\xB9\x40\x01')              # mov cx, 320
                            self.code.extend(b'\xF7\xE1')                  # mul cx
                            self.code.extend(b'\x01\xF8')                  # add ax, di
                            if offset_expr > 0:
                                self.code.extend(b'\x05' + offset_expr.to_bytes(2, 'little'))
                            self.code.extend(b'\x89\xC6')                  # mov si, ax
                            self.code.extend(b'\x26\xC6\x04' + bytes([vga_col]))

                # --- HAUPTSCHLEIFE ---
                loop_start = len(self.code)
                
                self.code.extend(b'\xE4\x64')              # in al, 0x64
                self.code.extend(b'\xA8\x01')              # test al, 1
                self.code.extend(b'\x0F\x84')              # jz near
                jz_pos = len(self.code)
                self.code.extend(b'\x00\x00')
                
                self.code.extend(b'\xE4\x60')              # Status verwerfen
                
                # Alten Hintergrund wiederherstellen
                for py in range(img_h - 1, -1, -1):
                    for px in range(img_w - 1, -1, -1):
                        r, g, b, a = pixels[px, py]
                        if a > 30:
                            offset_expr = py * 320 + px
                            self.code.extend(b'\x58')              # pop ax
                            self.code.extend(b'\x50')
                            self.code.extend(b'\x89\xE8')
                            self.code.extend(b'\xB9\x40\x01')
                            self.code.extend(b'\xF7\xE1')
                            self.code.extend(b'\x01\xF8')
                            if offset_expr > 0:
                                self.code.extend(b'\x05' + offset_expr.to_bytes(2, 'little'))
                            self.code.extend(b'\x89\xC6')
                            self.code.extend(b'\x58')
                            self.code.extend(b'\x26\x88\x04')

                # Delta X & Y lesen
                self.code.extend(b'\xE4\x60\x98\x01\xC7')  # Delta X zu DI
                self.code.extend(b'\xE4\x60\x98\x29\xC5')  # Delta Y von BP
                
                # Clamping X
                max_x = max(0, 320 - img_w)
                self.code.extend(b'\x81\xFF\x00\x00\x79')
                fix_x1 = len(self.code)
                self.code.extend(b'\x00')
                self.code.extend(b'\x31\xFF')
                target_x1 = len(self.code)
                self.code[fix_x1] = (target_x1 - (fix_x1 + 1)) & 0xFF

                self.code.extend(b'\x81\xFF' + max_x.to_bytes(2, 'little') + b'\x7E')
                fix_x2 = len(self.code)
                self.code.extend(b'\x00')
                self.code.extend(b'\xBF' + max_x.to_bytes(2, 'little'))
                target_x2 = len(self.code)
                self.code[fix_x2] = (target_x2 - (fix_x2 + 1)) & 0xFF

                # Clamping Y
                max_y = max(0, 200 - img_h)
                self.code.extend(b'\x81\xFD\x00\x00\x79')
                fix_y1 = len(self.code)
                self.code.extend(b'\x00')
                self.code.extend(b'\x31\xED')
                target_y1 = len(self.code)
                self.code[fix_y1] = (target_y1 - (fix_y1 + 1)) & 0xFF

                self.code.extend(b'\x81\xFD' + max_y.to_bytes(2, 'little') + b'\x7E')
                fix_y2 = len(self.code)
                self.code.extend(b'\x00')
                self.code.extend(b'\xBD' + max_y.to_bytes(2, 'little'))
                target_y2 = len(self.code)
                self.code[fix_y2] = (target_y2 - (fix_y2 + 1)) & 0xFF

                # Neuen Hintergrund sichern
                for py in range(img_h):
                    for px in range(img_w):
                        r, g, b, a = pixels[px, py]
                        if a > 30:
                            offset_expr = py * 320 + px
                            self.code.extend(b'\x89\xE8')
                            self.code.extend(b'\xB9\x40\x01')
                            self.code.extend(b'\xF7\xE1')
                            self.code.extend(b'\x01\xF8')
                            if offset_expr > 0:
                                self.code.extend(b'\x05' + offset_expr.to_bytes(2, 'little'))
                            self.code.extend(b'\x89\xC6')
                            self.code.extend(b'\x26\x8A\x04')
                            self.code.extend(b'\x50')

                # Neues Bild zeichnen
                for py in range(img_h):
                    for px in range(img_w):
                        r, g, b, a = pixels[px, py]
                        if a > 30:
                            vga_col = rgb_to_vga(r, g, b)
                            offset_expr = py * 320 + px
                            self.code.extend(b'\x89\xE8')
                            self.code.extend(b'\xB9\x40\x01')
                            self.code.extend(b'\xF7\xE1')
                            self.code.extend(b'\x01\xF8')
                            if offset_expr > 0:
                                self.code.extend(b'\x05' + offset_expr.to_bytes(2, 'little'))
                            self.code.extend(b'\x89\xC6')
                            self.code.extend(b'\x26\xC6\x04' + bytes([vga_col]))

                # Sprung zurück zum Schleifenanfang
                self.code.extend(b'\xE9')
                jmp_pos = len(self.code)
                self.code.extend(b'\x00\x00')
                
                jz_target = loop_start - (jz_pos + 2)
                self.code[jz_pos : jz_pos+2] = jz_target.to_bytes(2, 'little', signed=True)
                
                jmp_target = loop_start - (jmp_pos + 2)
                self.code[jmp_pos : jmp_pos+2] = jmp_target.to_bytes(2, 'little', signed=True)
            
            else:
                pass

        elif line == "stop":
            self.code.extend(b'\xFA\xF4\xEB\xFE')

    def save_boot_image(self, filename="os.bin"):
        self.code.extend(b'\xFA\xF4\xEB\xFE')
        
        stage2_bytes = self.code
        sector_size = 512
        num_sectors = (len(stage2_bytes) + sector_size - 1) // sector_size
        
        if num_sectors > 120:
            raise ValueError("Fehler: Zu viel Code!")

        stage2_bytes.extend(b'\x00' * (num_sectors * sector_size - len(stage2_bytes)))

        stage1 = bytearray()
        stage1.extend(b'\xFA')                      # cli
        stage1.extend(b'\x31\xC0\x8E\xD8\x8E\xC0')  # xor ax,ax; mov ds,ax; mov es,ax
        stage1.extend(b'\x8E\xD0\xBC\x00\x7C')      # mov ss,ax; mov sp,0x7C00
        
        stage1.extend(b'\xB4\x02')                  # mov ah, 2
        stage1.extend(b'\xB0' + bytes([num_sectors]))# mov al, anzahl sektoren
        stage1.extend(b'\xB5\x00')                  # mov ch, 0
        stage1.extend(b'\xB1\x02')                  # mov cl, 2
        stage1.extend(b'\xB6\x00')                  # mov dh, 0
        stage1.extend(b'\x68\x00\x10\x07')          # push 0x1000; pop es
        stage1.extend(b'\xBB\x00\x00')              # mov bx, 0x0000
        stage1.extend(b'\xCD\x13')                  # int 0x13
        stage1.extend(b'\x72\xFE')                  # jc $
        
        stage1.extend(b'\xEA\x00\x00\x00\x10')      # jmp 0x1000:0x0000

        stage1.extend(b'\x00' * (510 - len(stage1)))
        stage1.extend(b'\x55\xAA')

        final_image = stage1 + stage2_bytes

        with open(filename, "wb") as f:
            f.write(final_image)
        print(f"[ERFOLG]: Multi-Sector Image '{filename}' generiert ({len(final_image)} Bytes).")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Nutzung: python compiler.py <datei.lwkossl>")
        sys.exit(1)
        
    compiler = QemuOSCompiler()
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        for line in f:
            compiler.compile_line(line)
    
    compiler.save_boot_image("os.bin")