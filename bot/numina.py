# -*- coding: utf-8 -*-
import os
import io
import json
import math
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue
import pygame
import RPi.GPIO as GPIO

# Suppress luma initialization errors when desktop environment links are unavailable
os.environ["LUMA_NO_DISPLAY"] = "1"
from luma.core.interface.serial import noop, spi
from luma.core.render import canvas
from luma.led_matrix.device import max7219

def is_raspberry_pi_environment():
    try:
        with open("/proc/device-tree/model", "r", encoding="utf-8", errors="ignore") as handle:
            model = handle.read().strip()
        return "Raspberry Pi" in model
    except Exception:
        return False

def require_raspberry_pi_runtime():
    if not is_raspberry_pi_environment():
        raise RuntimeError("Numina must run on a physical Raspberry Pi 5.")

# ============================================================================== 
# 1. HARDWARE PIN ASSIGNMENTS
# ==============================================================================
START_PIN = 27
ESTOP_PIN = 22
A_PIN = 18
B_PIN = 23
C_PIN = 24
D_PIN = 25
MIC_SENSOR_PIN = 17

# ============================================================================== 
# 2. RUNTIME ASSET DIRECTORY CONVENTIONS
# ==============================================================================
NUMINA_HOME = os.environ.get("NUMINA_HOME", "/home/pi/numina")
AUDIO_INTRO = os.path.join(NUMINA_HOME, "audio", "lesson.mp3")
# Curriculum content: MATHS_ROOT/grade_<N>/<topic_folder>/{lesson.mp4,guide.mp3,fact.mp3,summary.mp3,quiz.json}
MATHS_ROOT = os.path.join(NUMINA_HOME, "maths")
GRADES = (9, 10, 11, 12)
CAPTURE_PATH = os.path.join(NUMINA_HOME, "capture", "problem_input.jpg")

# ============================================================================== 
# 3. GLOBAL GUI CONFIGURATIONS (Optimised for 5-inch 800x480 screen)
# ==============================================================================
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

# Refactored High-Contrast UI Color Palette
COLOR_BG = (15, 18, 26)         # Deepest charcoal black-blue
COLOR_CARD = (28, 33, 46)       # Subtle gray-blue for unselected container blocks
COLOR_TEXT = (240, 244, 255)     # Off-white crisp text
COLOR_ACCENT_BORDER = (0, 168, 204) # Electric educational cyan (idle state border)

# Dedicated Selector Colors
COLOR_SELECTED_BG = (0, 140, 170)   # Filled high-contrast selection background color
COLOR_SELECTED_TEXT = (255, 255, 255) # Pure white text inside selected block
COLOR_ALERT = (255, 75, 75)      # Red warning indicators

screen = None
font_title = None
font_body = None
device_matrix = None


def draw_matrix_glyph(glyph_type, selected_index=None):
    if device_matrix is None:
        return

    with canvas(device_matrix) as draw:
        if glyph_type == "menu":
            cells = [(1, 1), (5, 1), (1, 5), (5, 5)]
            for index, (x, y) in enumerate(cells):
                if selected_index == index:
                    for px in range(x, x + 2):
                        for py in range(y, y + 2):
                            draw.point((px, py), fill="white")
                else:
                    draw.point((x, y), fill="white")
        elif glyph_type == "idle":
            for x, y in [(3, 2), (2, 3), (3, 3), (4, 3), (3, 4)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "processing":
            for x in range(1, 7):
                draw.point((x, 3), fill="white")
                draw.point((x, 4), fill="white")
        elif glyph_type == "lesson":
            for y in range(1, 7):
                draw.point((2, y), fill="white")
            for x, y in [(3, 2), (3, 6), (4, 3), (4, 5), (5, 4)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "camera":
            for x in range(1, 7):
                draw.point((x, 2), fill="white")
                draw.point((x, 6), fill="white")
            for y in range(3, 6):
                draw.point((1, y), fill="white")
                draw.point((6, y), fill="white")
            for x, y in [(3, 3), (4, 3), (2, 4), (5, 4), (3, 5), (4, 5)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "complete":
            for x, y in [(1, 4), (2, 5), (3, 6), (4, 5), (5, 4), (6, 3), (7, 2)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "error":
            for index in range(1, 7):
                draw.point((index, index), fill="white")
                draw.point((index, 7 - index), fill="white")
        elif glyph_type == "listening":
            frame = selected_index or 0
            for x in range(8):
                height = 1 + ((x * 3 + frame) % 4)
                for offset in range(height):
                    draw.point((x, 3 - offset), fill="white")
                    draw.point((x, 4 + offset), fill="white")


def setup_hardware_and_gui():
    global device_matrix, screen, font_title, font_body
    require_raspberry_pi_runtime()

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [START_PIN, ESTOP_PIN, A_PIN, B_PIN, C_PIN, D_PIN, MIC_SENSOR_PIN]:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(ESTOP_PIN, GPIO.FALLING, callback=emergency_stop_callback, bouncetime=200)

    pygame.init()
    pygame.mixer.init()
    
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Numina Educational Engine v2.1")
    
    font_title = pygame.font.SysFont("Arial", 26, bold=True)
    font_body = pygame.font.SysFont("Arial", 18, bold=True)

    try:
        serial_spi = spi(port=0, device=0, gpio=noop())
        device_matrix = max7219(serial_spi, cascaded=1)
        device_matrix.contrast(30)
        draw_matrix_glyph("idle")
    except Exception as error:
        device_matrix = None
        print(f"MAX7219 matrix unavailable: {error}")

def emergency_stop_callback(channel):
    pygame.mixer.music.stop()
    os.system("pkill vlc || pkill cvlc || pkill rpicam-vid || pkill ffmpeg")
    pygame.quit()
    os._exit(0)

# ============================================================================== 
# 4. COMPREHENSIVE TEXT WRAPPING & UI RENDER INTERFACE
# ==============================================================================
def render_text_wrapped(surface, text, color, rect, font, line_spacing=4):
    """Splits long strings into words and fits them into specified button blocks cleanly."""
    words = text.split(' ')
    lines = []
    current_line = ""
    
    for word in words:
        test_line = current_line + " " + word if current_line else word
        test_surface = font.render(test_line, True, color)
        if test_surface.get_width() <= (rect[2] - 20):  # Leave a conservative 10px margin left/right
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    total_height = len(lines) * font.get_linesize() + (len(lines) - 1) * line_spacing
    start_y = rect[1] + (rect[3] - total_height) // 2  # Vertically centered inside the button block

    for line in lines:
        line_surface = font.render(line, True, color)
        start_x = rect[0] + (rect[2] - line_surface.get_width()) // 2  # Horizontally centered
        surface.blit(line_surface, (start_x, start_y))
        start_y += font.get_linesize() + line_spacing

def draw_ui_base(title_text):
    screen.fill(COLOR_BG)
    pygame.draw.rect(screen, COLOR_CARD, (0, 0, SCREEN_WIDTH, 70))
    title_surface = font_title.render(title_text, True, COLOR_TEXT)
    screen.blit(title_surface, (25, 20))
    pygame.draw.rect(screen, COLOR_ACCENT_BORDER, (0, 68, SCREEN_WIDTH, 2))

def draw_touch_button(rect, text, is_selected=False):
    """Draws a high-contrast button block with clean spacing and explicit color schemes."""
    if is_selected:
        bg_color = COLOR_SELECTED_BG
        border_color = COLOR_TEXT
        text_color = COLOR_SELECTED_TEXT
    else:
        bg_color = COLOR_CARD
        border_color = COLOR_ACCENT_BORDER
        text_color = COLOR_TEXT

    pygame.draw.rect(screen, bg_color, rect, border_radius=10)
    pygame.draw.rect(screen, border_color, rect, width=2, border_radius=10)
    
    render_text_wrapped(screen, text, text_color, rect, font_body)

def render_options_menu(title, options_list, selected_index=None):
    """Generates a balanced, spacious grid configuration layout across the screen."""
    draw_ui_base(title)
    draw_matrix_glyph("menu", selected_index)
    
    # 4 distinct layout blocks providing 30px spacing between margins and columns
    buttons = [
        (30, 110, 355, 130),   # Top Left Button [A]
        (415, 110, 355, 130),  # Top Right Button [B]
        (30, 280, 355, 130),   # Bottom Left Button [C]
        (415, 280, 355, 130)   # Bottom Right Button [D]
    ]
    
    active_buttons = []
    for idx, option in enumerate(options_list[:4]):
        rect = buttons[idx]
        is_sel = (selected_index == idx)
        draw_touch_button(rect, option, is_selected=is_sel)
        active_buttons.append((rect, idx))
        
    pygame.display.flip()
    return active_buttons

# ============================================================================== 
# 5. INPUT EVENT CONTROLLER LOOP (Unified Touchscreen & Hardware Control)
# ==============================================================================
def wait_for_ui_selection(active_buttons=None, physical_pins=None):
    while True:
        if physical_pins:
            for pin in physical_pins:
                if GPIO.input(pin) == GPIO.LOW:
                    time.sleep(0.15) # Optimized debouncing delay window
                    if GPIO.input(pin) == GPIO.LOW:
                        return ("hardware", pin)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
                
            if event.type == pygame.MOUSEBUTTONDOWN and active_buttons:
                mouse_pos = getattr(event, "pos", pygame.mouse.get_pos())
                for rect, idx in active_buttons:
                    x, y, w, h = rect
                    if x <= mouse_pos[0] <= x + w and y <= mouse_pos[1] <= y + h:
                        return ("touch", idx)
        time.sleep(0.01)

# ============================================================================== 
# 6. LEKKER MEDIA STREAMING ENGINE (640x360 Frame-Locked Resolution)
# ==============================================================================
def gui_play_video(file_path):
    """Play the lesson in an aspect-preserving viewport without blocking the UI."""
    draw_matrix_glyph("lesson")
    if not os.path.exists(file_path):
        time.sleep(2)
        return

    ffmpeg_binary = shutil.which("ffmpeg")
    if not ffmpeg_binary:
        print("Lesson playback requires ffmpeg.")
        return

    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="numina-lesson-", suffix=".wav", delete=False) as audio_file:
            audio_path = audio_file.name
        audio_result = subprocess.run(
            [ffmpeg_binary, "-y", "-i", file_path, "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", audio_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
        )
        if audio_result.returncode != 0 or os.path.getsize(audio_path) == 0:
            os.remove(audio_path)
            audio_path = None
        else:
            pygame.mixer.music.load(audio_path)
    except (OSError, pygame.error, subprocess.TimeoutExpired) as error:
        print(f"Lesson audio unavailable; continuing video playback: {error}")
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        audio_path = None

    v_w, v_h = 720, 340
    v_x, v_y = (SCREEN_WIDTH - v_w) // 2, 82
    frame_bytes = v_w * v_h * 3
    cmd = [
        ffmpeg_binary, "-re", "-i", file_path,
        "-vf", f"scale={v_w}:{v_h}:force_original_aspect_ratio=decrease,pad={v_w}:{v_h}:(ow-iw)/2:(oh-ih)/2:color=0x0f121a",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-vsync", "0", "-"
    ]
    try:
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    except OSError as error:
        print(f"Unable to start lesson video playback: {error}")
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        return

    if audio_path:
        pygame.mixer.music.play()

    frame_queue = queue.Queue(maxsize=2)
    reader_done = threading.Event()

    def read_frames():
        try:
            while True:
                frame = bytearray()
                while len(frame) < frame_bytes:
                    chunk = pipe.stdout.read(frame_bytes - len(frame))
                    if not chunk:
                        return
                    frame.extend(chunk)

                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    frame_queue.put_nowait(bytes(frame))
                except queue.Full:
                    pass
        finally:
            reader_done.set()

    reader_thread = threading.Thread(target=read_frames, daemon=True)
    reader_thread.start()

    draw_ui_base("Streaming Media Lesson Profile...")
    pygame.draw.rect(screen, COLOR_CARD, (v_x - 4, v_y - 4, v_w + 8, v_h + 8), border_radius=6)
    lbl = font_body.render("Tap screen anywhere to skip lesson video", True, COLOR_TEXT)
    screen.blit(lbl, (SCREEN_WIDTH // 2 - lbl.get_width() // 2, 452))
    pygame.display.flip()

    clock = pygame.time.Clock()
    running_video = True
    try:
        while running_video:
            for event in pygame.event.get():
                if event.type == pygame.MOUSEBUTTONDOWN:
                    running_video = False

            raw_image = None
            while True:
                try:
                    raw_image = frame_queue.get_nowait()
                except queue.Empty:
                    break

            if raw_image is not None:
                video_surface = pygame.image.frombuffer(raw_image, (v_w, v_h), "RGB").copy()
                screen.blit(video_surface, (v_x, v_y))
                pygame.display.update((v_x - 4, v_y - 4, v_w + 8, v_h + 8))

            if reader_done.is_set() and frame_queue.empty():
                break

            clock.tick(60)
    finally:
        pipe.terminate()
        try:
            pipe.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pipe.kill()
            pipe.wait()
        reader_thread.join(timeout=1)
        if audio_path:
            pygame.mixer.music.stop()
            try:
                os.remove(audio_path)
            except FileNotFoundError:
                pass

# ==============================================================================
# LIVE CAMERA PREVIEW BEFORE CAPTURE MODULE
# ==============================================================================
def extract_mjpeg_frames(buffer):
    """Return complete JPEG frames and retain any incomplete trailing frame."""
    frames = []
    while True:
        start = buffer.find(b'\xff\xd8')
        if start == -1:
            keep_marker_prefix = buffer[-1:] == b'\xff'
            buffer[:] = buffer[-1:] if keep_marker_prefix else b''
            break
        if start:
            del buffer[:start]

        end = buffer.find(b'\xff\xd9', 2)
        if end == -1:
            break
        frames.append(bytes(buffer[:end + 2]))
        del buffer[:end + 2]
    return frames


def gui_live_camera_capture_flow(output_path):
    """Show a steady live preview, then save a full-resolution still image."""
    draw_matrix_glyph("camera")
    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    temporary_path = output_path + ".tmp.jpg"
    for stale_path in (output_path, temporary_path):
        try:
            os.remove(stale_path)
        except FileNotFoundError:
            pass

    c_w, c_h = 480, 270
    c_x, c_y = 40, 110
    video_binary = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
    still_binary = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if not video_binary or not still_binary:
        print("Camera capture requires rpicam-apps or the legacy libcamera-apps.")
        return False

    cmd = [
        video_binary, "-t", "0", "--width", str(c_w), "--height", str(c_h),
        "--nopreview", "--codec", "mjpeg", "-o", "-"
    ]
    try:
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    except OSError as error:
        print(f"Unable to start camera preview: {error}")
        return False

    btn_rect = (540, 220, 220, 70)
    clock = pygame.time.Clock()
    awaiting_capture = True
    capture_requested = False
    buffer = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(pipe.stdout, selectors.EVENT_READ)

    draw_ui_base("Live Preview: Align Problem Sheet")
    pygame.draw.rect(screen, COLOR_CARD, (c_x - 4, c_y - 4, c_w + 8, c_h + 8), border_radius=6)
    waiting_label = font_body.render("Waiting for camera frames...", True, COLOR_TEXT)
    screen.blit(waiting_label, (c_x + 110, c_y + 120))
    render_text_wrapped(screen, "Center problem code sheet in frame", COLOR_TEXT, (40, 390, 480, 40), font_body)
    draw_touch_button(btn_rect, "SNAP IMAGE [D]", is_selected=True)
    pygame.display.flip()

    try:
        while awaiting_capture:
            for event in pygame.event.get():
                if event.type == pygame.MOUSEBUTTONDOWN:
                    mouse_pos = pygame.mouse.get_pos()
                    x, y, w, h = btn_rect
                    if x <= mouse_pos[0] <= x + w and y <= mouse_pos[1] <= y + h:
                        awaiting_capture = False
                        capture_requested = True

            if GPIO.input(START_PIN) == GPIO.LOW or GPIO.input(D_PIN) == GPIO.LOW:
                awaiting_capture = False
                capture_requested = True

            if selector.select(timeout=0):
                chunk = os.read(pipe.stdout.fileno(), 65536)
                if not chunk:
                    awaiting_capture = False
                    continue
                buffer.extend(chunk)
                frames = extract_mjpeg_frames(buffer)
                if len(buffer) > 4 * 1024 * 1024:
                    buffer.clear()

                if frames:
                    try:
                        img_surface = pygame.image.load(io.BytesIO(frames[-1])).convert()
                        img_surface = pygame.transform.smoothscale(img_surface, (c_w, c_h))
                    except (pygame.error, ValueError):
                        img_surface = None

                    if img_surface:
                        pygame.draw.rect(screen, COLOR_CARD, (c_x - 4, c_y - 4, c_w + 8, c_h + 8), border_radius=6)
                        screen.blit(img_surface, (c_x, c_y))
                        pygame.display.update((c_x - 4, c_y - 4, c_w + 8, c_h + 8))
            elif pipe.poll() is not None:
                awaiting_capture = False

            clock.tick(30)

    finally:
        selector.close()
        pipe.terminate()
        try:
            pipe.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pipe.kill()
            pipe.wait()

    if not capture_requested:
        return False

    status_rect = (530, 310, 250, 60)
    draw_matrix_glyph("processing")
    pygame.draw.rect(screen, COLOR_BG, status_rect)
    status_label = font_body.render("Capturing full-resolution image...", True, COLOR_TEXT)
    screen.blit(status_label, (540, 325))
    pygame.display.update(status_rect)

    still_cmd = [still_binary, "-t", "1000", "--nopreview", "-o", temporary_path]
    try:
        result = subprocess.run(still_cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Still image capture failed: {error}")
        return False

    if result.returncode != 0 or not os.path.isfile(temporary_path) or os.path.getsize(temporary_path) == 0:
        if result.stderr:
            print(f"Still image capture failed: {result.stderr.strip()}")
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass
        return False

    os.replace(temporary_path, output_path)
    return True

OCR_OPERATOR_MAP = {
    "\u00d7": "*", "\u2715": "*", "\u00b7": "*", "\u00f7": "/", "\u2212": "-", "\u2013": "-", "\u2014": "-",
    "\u2236": ":", "X": "x", "\u00ab": "", "\u00bb": "",
}


def preprocess_image_for_ocr(image_path):
    """Return the path of a grayscale, contrast-stretched, binarised copy suited to OCR."""
    from PIL import Image, ImageFilter, ImageOps

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("L")
    longest = max(image.size)
    if longest > 2400 or longest < 1400:
        scale = 2000 / longest
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)
    image = ImageOps.autocontrast(image, cutoff=2).filter(ImageFilter.MedianFilter(3))
    histogram = image.histogram()
    total = sum(histogram)
    sum_all = sum(i * count for i, count in enumerate(histogram))
    background = weight_bg = 0
    best_variance = threshold = 0
    for level, count in enumerate(histogram):
        weight_bg += count
        if weight_bg == 0 or weight_bg == total:
            continue
        background += level * count
        mean_bg = background / weight_bg
        mean_fg = (sum_all - background) / (total - weight_bg)
        variance = weight_bg * (total - weight_bg) * (mean_bg - mean_fg) ** 2
        if variance > best_variance:
            best_variance, threshold = variance, level
    image = image.point(lambda value: 255 if value > threshold else 0)
    processed_path = image_path + ".ocr.png"
    image.save(processed_path)
    return processed_path


def run_tesseract(image_path, page_segmentation_mode, whitelist=None):
    command = ["tesseract", image_path, "stdout", "--psm", str(page_segmentation_mode)]
    if whitelist:
        command += ["-c", f"tessedit_char_whitelist={whitelist}"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    return result.stdout if result.returncode == 0 else ""


def normalize_ocr_line(line):
    for source, target in OCR_OPERATOR_MAP.items():
        line = line.replace(source, target)
    line = re.sub(r"[|_~`]", "", line)
    line = re.sub(r"(?<=[\dx)])\s*[:]\s*(?=[\dx(])", "/", line)
    line = re.sub(r"x{2,}", "x", line)
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"^(?:solve|find x|question\s*\d*|q\d+)\s*[:.)-]?\s*", "", line, flags=re.IGNORECASE)
    return line.strip()


def interpret_captured_image(image_path):
    """OCR a captured problem and solve it. Returns dict with text, problem, steps, spoken, error."""
    outcome = {"text": "", "problem": None, "steps": [], "spoken": "", "error": None}
    if not os.path.isfile(image_path):
        outcome["error"] = "No captured image to read."
        return outcome
    if not shutil.which("tesseract"):
        outcome["error"] = "Image reader missing. Run: sudo apt install -y tesseract-ocr"
        return outcome

    processed_path = None
    try:
        processed_path = preprocess_image_for_ocr(image_path)
        passes = (
            (6, "0123456789xX+-*/=().^\u00d7\u00f7\u2212"),
            (7, "0123456789xX+-*/=().^\u00d7\u00f7\u2212"),
            (6, None),
        )
        readings = []
        for mode, whitelist in passes:
            raw = run_tesseract(processed_path, mode, whitelist)
            lines = [normalize_ocr_line(line) for line in raw.splitlines()]
            lines = [line for line in lines if line]
            if lines and not readings:
                readings.append(" / ".join(lines))
            for line in lines:
                solution = solve_linear_equation_text(line) if "=" in line else None
                if solution:
                    outcome.update(text=line, problem=line, steps=solution[0], spoken=solution[1])
                    return outcome
        outcome["text"] = readings[0] if readings else ""
        outcome["error"] = (
            "I could not read a solvable equation." if readings
            else "No writing was detected. Retake in good light, flat and in focus."
        )
    except ImportError:
        outcome["error"] = "Image tools missing. Run: pip install Pillow"
    except (OSError, subprocess.TimeoutExpired) as error:
        outcome["error"] = f"Image reading failed: {error}"
    finally:
        if processed_path and os.path.exists(processed_path):
            os.remove(processed_path)
    return outcome


def gui_show_captured_image(image_path):
    """Interpret the captured photo and show the worked solution. Returns 'retake' or 'continue'."""
    draw_matrix_glyph("processing")
    draw_ui_base("Reading your problem...")
    pygame.display.flip()
    outcome = interpret_captured_image(image_path)
    draw_matrix_glyph("complete")
    draw_ui_base("Scanned Problem")

    try:
        img = pygame.transform.scale(pygame.image.load(image_path), (340, 255))
        screen.blit(img, (30, 90))
    except Exception:
        pygame.draw.rect(screen, COLOR_CARD, (30, 90, 340, 255), border_radius=8)

    pygame.draw.rect(screen, COLOR_CARD, (390, 90, 380, 255), border_radius=8)
    if outcome["error"]:
        render_text_wrapped(screen, outcome["error"], COLOR_ALERT, (395, 100, 370, 90), font_body)
        if outcome["text"]:
            render_text_wrapped(screen, f"Read: {outcome['text']}", COLOR_TEXT, (395, 195, 370, 90), font_body)
        spoken = "I could not read that problem. Please retake the picture."
    else:
        render_text_wrapped(screen, f"Problem: {outcome['problem']}", COLOR_SELECTED_BG, (395, 100, 370, 50), font_body)
        for index, step in enumerate(outcome["steps"]):
            render_text_wrapped(screen, step, COLOR_TEXT, (395, 155 + index * 45, 370, 45), font_body)
        spoken = outcome["spoken"]

    retake_rect = (30, 370, 355, 85)
    continue_rect = (415, 370, 355, 85)
    draw_touch_button(retake_rect, "Retake Photo [A]")
    draw_touch_button(continue_rect, "Continue [D]", is_selected=True)
    pygame.display.flip()
    threading.Thread(target=speak_answer, args=(spoken,), daemon=True).start()
    src, value = wait_for_ui_selection(
        active_buttons=[(retake_rect, 0), (continue_rect, 1)], physical_pins=[A_PIN, D_PIN, START_PIN]
    )
    wanted_retake = value == 0 if src == "touch" else value == A_PIN
    return "retake" if wanted_retake else "continue"


def find_microphone_device_index(recognition_module):
    device_names = recognition_module.Microphone.list_microphone_names()
    configured_index = os.getenv("NUMINA_MIC_DEVICE_INDEX")
    if configured_index:
        index = int(configured_index)
        if index < 0 or index >= len(device_names):
            raise RuntimeError(f"NUMINA_MIC_DEVICE_INDEX {index} is not an available input device.")
        return index, device_names[index]

    for index, name in enumerate(device_names):
        if name and any(token in name.casefold() for token in ("pico", "usb", "pnp")):
            return index, name
    return None, "system default input"


def transcribe_question(result_queue):
    try:
        import speech_recognition as sr

        device_index, device_name = find_microphone_device_index(sr)
        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 0.8
        with sr.Microphone(device_index=device_index, sample_rate=16000, chunk_size=1024) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=12)

        recognition = recognizer.recognize_vosk(audio)
        if isinstance(recognition, dict):
            transcript = recognition.get("text", "").strip()
        else:
            try:
                transcript = json.loads(recognition).get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                transcript = recognition.strip()
        result_queue.put({"transcript": transcript, "device": device_name})
    except Exception as error:
        result_queue.put({"error": str(error)})


def solve_spoken_linear_equation(question):
    return solve_linear_equation_text(question)


def solve_linear_equation_text(question):
    expression = question.casefold().strip()
    expression = re.sub(r"[?,.!]", " ", expression)
    for spoken, symbol in (
        ("multiplied by", "*"), ("times", "*"), ("plus", "+"),
        ("minus", "-"), ("divided by", "/"), ("over", "/"),
        ("equals", "="), ("equal to", "="), ("is equal to", "="),
    ):
        expression = re.sub(rf"\b{re.escape(spoken)}\b", symbol, expression)
    expression = re.sub(r"\b(?:solve|what is|please|the equation|find)\b", " ", expression)
    expression = re.sub(r"\s+", " ", expression).strip()
    expression = re.sub(r"(?<=\d)\s+(?=x\b)", "*", expression)
    expression = expression.replace("^", "**")

    if expression.count("=") != 1 or not re.fullmatch(r"[0-9x+*/().=\-\s*]+", expression):
        return None

    left_text, right_text = expression.split("=", maxsplit=1)
    if not left_text.strip() or not right_text.strip():
        return None

    try:
        from sympy import Poly, Symbol, expand, simplify
        from sympy.parsing.sympy_parser import (
            convert_xor,
            implicit_multiplication_application,
            parse_expr,
            standard_transformations,
        )

        variable = Symbol("x")
        transformations = standard_transformations + (
            implicit_multiplication_application,
            convert_xor,
        )
        left = parse_expr(left_text, local_dict={"x": variable}, transformations=transformations)
        right = parse_expr(right_text, local_dict={"x": variable}, transformations=transformations)
        polynomial = Poly(expand(left - right), variable)
        if polynomial.degree() > 1:
            return None

        coefficient = polynomial.coeff_monomial(variable)
        constant = polynomial.coeff_monomial(1)
        if coefficient == 0:
            return None

        solution = simplify(-constant / coefficient)
        moved_constant = simplify(-constant)
        steps = [
            f"Start with {left} = {right}.",
            f"Combine like terms: {coefficient}x = {moved_constant}.",
            f"Divide both sides by {coefficient}.",
            f"Solution: x = {solution}.",
        ]
        spoken_answer = f"The answer is x equals {solution}. " + " ".join(steps[1:3])
        return steps, spoken_answer
    except Exception:
        return None


def speak_answer(text):
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as error:
        print(f"Offline speech output unavailable: {error}")


def gui_ask_question_flow():
    draw_matrix_glyph("listening", 0)
    question_queue = queue.Queue(maxsize=1)
    listener = threading.Thread(target=transcribe_question, args=(question_queue,), daemon=True)
    listener.start()

    clock = pygame.time.Clock()
    animation_start = time.monotonic()
    result = None
    while listener.is_alive() or question_queue.empty():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)

        elapsed = time.monotonic() - animation_start
        draw_ui_base("Ask Numina")
        pygame.draw.rect(screen, COLOR_CARD, (70, 105, 660, 285), border_radius=14)
        pygame.draw.circle(screen, COLOR_SELECTED_BG, (SCREEN_WIDTH // 2, 205), 56 + int(8 * math.sin(elapsed * 3)))
        pygame.draw.circle(screen, COLOR_BG, (SCREEN_WIDTH // 2, 205), 38)

        for bar in range(24):
            height = 12 + int(42 * abs(math.sin(elapsed * 4 + bar * 0.42)))
            x = 160 + bar * 21
            pygame.draw.line(screen, COLOR_ACCENT_BORDER, (x, 310 - height // 2), (x, 310 + height // 2), 5)

        title = font_title.render("Listening", True, COLOR_TEXT)
        hint = font_body.render("Ask a question or say a one-variable equation", True, COLOR_TEXT)
        timing = font_body.render("Speak naturally; pause when finished (up to 12 seconds)", True, COLOR_TEXT)
        screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 145))
        screen.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, 265))
        screen.blit(timing, (SCREEN_WIDTH // 2 - timing.get_width() // 2, 350))
        pygame.display.flip()
        draw_matrix_glyph("listening", int(elapsed * 8) % 8)

        try:
            result = question_queue.get_nowait()
            break
        except queue.Empty:
            pass
        clock.tick(30)

    if result is None:
        result = question_queue.get()

    draw_matrix_glyph("processing")
    if result.get("error"):
        message = result["error"]
        draw_ui_base("Microphone or speech model unavailable")
        render_text_wrapped(screen, message, COLOR_ALERT, (60, 135, 680, 140), font_body)
        render_text_wrapped(screen, "Check the USB microphone, PyAudio, and the offline Vosk model.", COLOR_TEXT, (60, 290, 680, 70), font_body)
        transcript = ""
        steps = ["No question was processed."]
        spoken_answer = "Please check the microphone and offline speech model setup."
    else:
        transcript = result.get("transcript", "")
        solution = solve_spoken_linear_equation(transcript) if transcript else None
        draw_ui_base("Question and Solution")
        pygame.draw.rect(screen, COLOR_CARD, (40, 100, 720, 300), border_radius=12)
        render_text_wrapped(screen, f"I heard: {transcript or 'No clear speech detected.'}", COLOR_TEXT, (65, 120, 670, 75), font_body)
        if solution:
            steps, spoken_answer = solution
            for index, step in enumerate(steps):
                render_text_wrapped(screen, step, COLOR_SELECTED_BG if index == len(steps) - 1 else COLOR_TEXT, (65, 205 + index * 38, 670, 38), font_body)
        else:
            steps = [
                "This offline build currently solves one-variable linear equations.",
                "Try: 3x plus 9 equals 24.",
                "General geometry, physics, and chemistry answers need a local AI model.",
            ]
            spoken_answer = "I heard your question, but this offline build currently solves one-variable linear equations."
            for index, step in enumerate(steps):
                render_text_wrapped(screen, step, COLOR_TEXT, (65, 220 + index * 42, 670, 42), font_body)

    btn_rect = (250, 415, 300, 48)
    draw_touch_button(btn_rect, "Continue", is_selected=True)
    pygame.display.flip()
    threading.Thread(target=speak_answer, args=(spoken_answer,), daemon=True).start()
    wait_for_ui_selection(active_buttons=[(btn_rect, 0)], physical_pins=[START_PIN])


BACK = "back"


def choose_from_menu(title, items, allow_back=True):
    """Paged 4-slot menu. Returns the chosen item index, or BACK. Slot D is always Back when allowed."""
    slots = 4 - (1 if allow_back else 0)
    paged = len(items) > slots
    per_page = slots - (1 if paged else 0)
    page = 0
    pins = [A_PIN, B_PIN, C_PIN, D_PIN]
    while True:
        start = page * per_page
        visible = items[start:start + per_page] if paged else items
        labels = list(visible)
        if paged:
            labels.append("More...")
        entries = [("item", start + i) for i in range(len(visible))]
        if paged:
            entries.append(("more", None))
        if allow_back:
            while len(labels) < 3:
                labels.append("")
                entries.append(("none", None))
            labels.append("< Back")
            entries.append(("back", None))

        buttons = render_options_menu(title, labels)
        buttons = [(rect, i) for rect, i in buttons if entries[i][0] != "none"]
        src, idx = wait_for_ui_selection(active_buttons=buttons, physical_pins=pins)
        slot = idx if src == "touch" else pins.index(idx)
        if slot >= len(entries):
            continue
        kind, value = entries[slot]
        if kind == "none":
            continue
        render_options_menu(title, labels, selected_index=slot)
        time.sleep(0.3)
        if kind == "back":
            return BACK
        if kind == "more":
            page = (page + 1) % ((len(items) + per_page - 1) // per_page)
            continue
        return value


def list_topics(grade):
    """Return [(display_name, folder_path)] for each topic folder under MATHS_ROOT/grade_<N>."""
    grade_dir = os.path.join(MATHS_ROOT, f"grade_{grade}")
    try:
        names = sorted(n for n in os.listdir(grade_dir) if os.path.isdir(os.path.join(grade_dir, n)))
    except OSError:
        return []
    return [(re.sub(r"^\d+[_-]", "", n).replace("_", " ").title(), os.path.join(grade_dir, n)) for n in names]


def load_quiz(topic_dir):
    try:
        with open(os.path.join(topic_dir, "quiz.json"), "r", encoding="utf-8") as handle:
            quiz = json.load(handle)
        options = [str(o) for o in quiz["options"]][:4]
        answer = int(quiz["answer"])
        if quiz.get("question") and len(options) >= 2 and 0 <= answer < len(options):
            return {"question": str(quiz["question"]), "options": options, "answer": answer,
                    "explanation": str(quiz.get("explanation", ""))}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def gui_message(title, message, color=None):
    draw_ui_base(title)
    render_text_wrapped(screen, message, color or COLOR_TEXT, (60, 130, 680, 200), font_body)
    btn_rect = (250, 380, 300, 60)
    draw_touch_button(btn_rect, "Continue", is_selected=True)
    pygame.display.flip()
    wait_for_ui_selection(active_buttons=[(btn_rect, 0)], physical_pins=[START_PIN])


def run_lesson(topic_name, topic_dir):
    guide, video, fact, summary = (os.path.join(topic_dir, n) for n in ("guide.mp3", "lesson.mp4", "fact.mp3", "summary.mp3"))
    if not os.path.isfile(video):
        gui_message(topic_name, "No lesson video has been added to this topic folder yet.", COLOR_ALERT)
        return
    play_audio(guide)
    gui_play_video(video)
    quiz = load_quiz(topic_dir)
    if quiz:
        pick = choose_from_menu(f"Quiz: {quiz['question']}", quiz["options"], allow_back=False)
        correct = pick == quiz["answer"]
        gui_message("Correct!" if correct else "Not quite",
                    quiz["explanation"] or f"The answer is: {quiz['options'][quiz['answer']]}",
                    COLOR_SELECTED_BG if correct else COLOR_ALERT)
    play_audio(fact)
    play_audio(summary)


def run_scanner():
    while True:
        if not gui_live_camera_capture_flow(CAPTURE_PATH):
            return
        if gui_show_captured_image(CAPTURE_PATH) != "retake":
            return


def play_audio(file_path):
    if not os.path.exists(file_path): return
    try:
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
    except Exception: pass

# ============================================================================== 
# 7. MAIN PROGRAM EXECUTION LOOP
# ==============================================================================
def run_numina_engine():
    setup_hardware_and_gui()

    while True:
        if True:
            # 1. STANDBY WELCOME LAYOUT SCREEN
            draw_matrix_glyph("idle")
            screen.fill(COLOR_BG)
            pygame.draw.rect(screen, COLOR_CARD, (50, 50, 700, 380), border_radius=16)
            
            t_surf = font_title.render("NUMINA BOT CORE SYSTEMS OPERATIONAL", True, COLOR_SELECTED_BG)
            b_surf = font_body.render("Press physical START button or tap screen to wake engine", True, COLOR_TEXT)
            screen.blit(t_surf, (SCREEN_WIDTH//2 - t_surf.get_width()//2, 160))
            screen.blit(b_surf, (SCREEN_WIDTH//2 - b_surf.get_width()//2, 240))
            pygame.display.flip()
            
            wait_for_ui_selection(active_buttons=[((50, 50, 700, 380), 0)], physical_pins=[START_PIN])
            draw_matrix_glyph("processing")
            play_audio(AUDIO_INTRO)

        # 2-4. GRADE -> TOPIC -> MODE, each with Back navigation
        stage, grade, topic = "grade", None, None
        while True:
            if stage == "grade":
                pick = choose_from_menu("Select Grade", [f"Grade {g}" for g in GRADES], allow_back=False)
                grade, stage = GRADES[pick], "topic"
            elif stage == "topic":
                topics = list_topics(grade)
                if not topics:
                    gui_message(f"Grade {grade}", f"No topic folders found in {os.path.join(MATHS_ROOT, f'grade_{grade}')}", COLOR_ALERT)
                    stage = "grade"
                    continue
                pick = choose_from_menu(f"Grade {grade}: Choose a Topic", [t[0] for t in topics])
                if pick == BACK:
                    stage = "grade"
                else:
                    topic, stage = topics[pick], "mode"
            else:
                modes = ["Watch Lesson", "Scan a Problem", "Ask a Question"]
                pick = choose_from_menu(f"{topic[0]}: What next?", modes)
                if pick == BACK:
                    stage = "topic"
                elif pick == 0:
                    run_lesson(topic[0], topic[1])
                elif pick == 1:
                    run_scanner()
                else:
                    gui_ask_question_flow()
                draw_matrix_glyph("complete")

if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
