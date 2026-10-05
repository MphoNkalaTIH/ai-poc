# -*- coding: utf-8 -*-
import os
import io
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
AUDIO_INTRO = "/home/pi/numina/audio/lesson.mp3"
AUDIO_GUIDE = "/home/pi/numina/audio/guide_step.mp3"
AUDIO_FACT = "/home/pi/numina/audio/fun_fact.mp3"
AUDIO_SUMMARY = "/home/pi/numina/audio/summary.mp3"
VIDEO_LESSON = "/home/pi/numina/video/lesson.mp4"
CAPTURE_PATH = "/home/pi/numina/capture/problem_input.jpg"

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
        device_matrix.clear()
    except Exception:
        device_matrix = None

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

def gui_show_captured_image(image_path):
    draw_ui_base("Analytical Workspace Capture Resolved")
    
    if os.path.exists(image_path):
        try:
            img = pygame.image.load(image_path)
            img = pygame.transform.scale(img, (400, 300))
            screen.blit(img, (40, 110))
        except Exception:
            pass
    else:
        pygame.draw.rect(screen, COLOR_CARD, (40, 110, 400, 300), border_radius=8)
        lbl = font_body.render("[Missing Capture Data Frame Asset]", True, COLOR_ALERT)
        screen.blit(lbl, (100, 230))

    pygame.draw.rect(screen, COLOR_CARD, (480, 110, 280, 300), border_radius=8)
    lines = ["[ANALYSIS MATCHED]", "Problem: 3x + 9 = 24", "", "Step 1: Subtract 9", "        3x = 15", "Step 2: Divide by 3", "        x = 5"]
    for i, line in enumerate(lines):
        color = COLOR_SELECTED_BG if i == 1 else COLOR_TEXT
        text_surf = font_body.render(line, True, color)
        screen.blit(text_surf, (500, 130 + (i * 30)))

    btn_rect = (480, 350, 280, 60)
    draw_touch_button(btn_rect, "Continue", is_selected=True)
    pygame.display.flip()
    
    wait_for_ui_selection(active_buttons=[(btn_rect, 0)], physical_pins=[START_PIN])

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
    skip_standby = False

    while True:
        if not skip_standby:
            # 1. STANDBY WELCOME LAYOUT SCREEN
            screen.fill(COLOR_BG)
            pygame.draw.rect(screen, COLOR_CARD, (50, 50, 700, 380), border_radius=16)
            
            t_surf = font_title.render("NUMINA BOT CORE SYSTEMS OPERATIONAL", True, COLOR_SELECTED_BG)
            b_surf = font_body.render("Press physical START button or tap screen to wake engine", True, COLOR_TEXT)
            screen.blit(t_surf, (SCREEN_WIDTH//2 - t_surf.get_width()//2, 160))
            screen.blit(b_surf, (SCREEN_WIDTH//2 - b_surf.get_width()//2, 240))
            pygame.display.flip()
            
            wait_for_ui_selection(active_buttons=[((50, 50, 700, 380), 0)], physical_pins=[START_PIN])
            play_audio(AUDIO_INTRO)
        skip_standby = False

        # 2. SELECT GRADE INTERFACE PANEL
        menu_items = ["Grade 9 Curriculum", "Grade 10 Curriculum", "Grade 11 Curriculum", "Grade 12 Curriculum"]
        btns = render_options_menu("Select Educational Curriculum Target Level", menu_items)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_idx = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)
        
        # Redraw with selected indicator state briefly before proceeding
        render_options_menu("Select Educational Curriculum Target Level", menu_items, selected_index=chosen_idx)
        time.sleep(0.4)

        # 3. SELECT DOMAIN CONCEPT MATRIX TRACKER
        concepts = ["Linear Algebra", "Geometry Proofs", "Physics Dynamics", "Chemistry Moles"]
        btns = render_options_menu("Select Domain Subject Concept Study Module", concepts)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_concept_idx = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)
        
        render_options_menu("Select Domain Subject Concept Study Module", concepts, selected_index=chosen_concept_idx)
        time.sleep(0.4)

        # 4. PATH TRACK SELECTOR ROUTER
        paths = ["Run Core Lesson Video Package", "Deploy Analytical Scanner Environment", "Cancel Selection", "Return to Idle Loop"]
        btns = render_options_menu("Choose Interaction Path Mode Pipeline", paths)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_path = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)
        
        render_options_menu("Choose Interaction Path Mode Pipeline", paths, selected_index=chosen_path)
        time.sleep(0.4)

        if chosen_path == 0:
            # ---- TRACK A: VIDEO ENGINE LECTURE MODULE ----
            play_audio(AUDIO_GUIDE)
            gui_play_video(VIDEO_LESSON)
            
            quiz_opts = ["Always True (Option A)", "Conditional Variant (Option B)", "Never True (Option C)", "Insufficient Core Telemetry (Option D)"]
            btns = render_options_menu("Assessment Validation Q1: Is this homogeneous?", quiz_opts)
            wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
            play_audio(AUDIO_FACT)
        else:
            # ---- TRACK B: CAMERA LIVE PREVIEW & CAPTURE MODULE ----
            gui_live_camera_capture_flow(CAPTURE_PATH)
            gui_show_captured_image(CAPTURE_PATH)

        # 5. SESSION CLOSEOUT AND NEXT-STEP CHOICE
        play_audio(AUDIO_SUMMARY)
        while True:
            next_steps = ["Capture Another Problem", "Return to Categories"]
            btns = render_options_menu("Session Complete: Choose Next Step", next_steps)
            src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
            next_step = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)

            if next_step == 1:
                skip_standby = True
                break

            if gui_live_camera_capture_flow(CAPTURE_PATH):
                gui_show_captured_image(CAPTURE_PATH)

if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
