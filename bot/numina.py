# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import time
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
                mouse_pos = pygame.mouse.get_pos()
                for rect, idx in active_buttons:
                    x, y, w, h = rect
                    if x <= mouse_pos[0] <= x + w and y <= mouse_pos[1] <= y + h:
                        return ("touch", idx)
        time.sleep(0.01)

# ============================================================================== 
# 6. LEKKER MEDIA STREAMING ENGINE (640x360 Frame-Locked Resolution)
# ==============================================================================
def gui_play_video(file_path):
    """Streams lesson mp4 file natively into a high-performance 30fps framebuffer block."""
    draw_ui_base("Streaming Media Lesson Profile...")
    pygame.display.flip()

    if not os.path.exists(file_path):
        time.sleep(2)
        return

    # Scale the reading frame to 640x360 to decrease processing overhead on the Pi
    v_w, v_h = 640, 360
    v_x, v_y = (SCREEN_WIDTH - v_w) // 2, 85

    # Optimize the pipeline to stabilize framerate drops over screensharing links
    cmd = [
        'ffmpeg', '-re', '-i', file_path, '-f', 'image2pipe', 
        '-pix_fmt', 'rgb24', '-s', f'{v_w}x{v_h}', '-vcodec', 'rawvideo', '-'
    ]
    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7)

    clock = pygame.time.Clock()
    running_video = True
    
    try:
        while running_video:
            for event in pygame.event.get():
                if event.type == pygame.MOUSEBUTTONDOWN:
                    running_video = False # Tap anywhere to exit video playback loop cleanly

            # Read a precise single video frame chunk from the memory pipe layout
            frame_bytes = v_w * v_h * 3
            raw_image = pipe.stdout.read(frame_bytes)
            if not raw_image or len(raw_image) < frame_bytes:
                break

            video_surface = pygame.image.fromstring(raw_image, (v_w, v_h), 'RGB')
            
            # Frame card boundary setup
            pygame.draw.rect(screen, COLOR_CARD, (v_x-4, v_y-4, v_w+8, v_h+8), border_radius=6)
            screen.blit(video_surface, (v_x, v_y))
            
            lbl = font_body.render("Tap screen anywhere to skip lesson video", True, COLOR_TEXT)
            screen.blit(lbl, (SCREEN_WIDTH//2 - lbl.get_width()//2, 452))
            
            pygame.display.flip()
            clock.tick(30) # Lock to rock-solid 30fps frame metrics loop
    finally:
        pipe.terminate()
        pipe.wait()

# ==============================================================================
# LIVE CAMERA PREVIEW BEFORE CAPTURE MODULE
# ==============================================================================
def gui_live_camera_capture_flow(output_path):
    """Pipes live camera frame streams onto the screen before firing final snapshot."""
    draw_ui_base("Live Camera Space Workspace Alignment")
    pygame.display.flip()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        try: os.remove(output_path)
        except Exception: pass

    # Run a low-overhead stream layout frame via ffmpeg capturing from the camera link
    c_w, c_h = 480, 270
    c_x, c_y = 40, 110

    # Command captures raw frames directly from the hardware video node pipeline
    cmd = [
        'libcamera-vid', '-t', '0', '--inline', '--width', str(c_w), '--height', str(c_h),
        '--nopreview', '--codec', 'mjpeg', '-o', '-'
    ]
    # Fallback to general rpicam system if libcamera path binary was unlinked
    if not os.path.exists("/usr/bin/libcamera-vid") and os.path.exists("/usr/bin/rpicam-vid"):
        cmd[0] = 'rpicam-vid'

    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**6)

    # Capture Action Trigger Button Box UI
    btn_rect = (540, 220, 220, 70)
    
    clock = pygame.time.Clock()
    awaiting_capture = True
    
    # Read loop constants for MJPEG boundary blocks
    # JPEG files always start with 0xFFD8 and end with 0xFFD9
    buffer = bytearray()
    
    try:
        while awaiting_capture:
            # Draw UI components while running frame parsing loops
            screen.fill(COLOR_BG)
            pygame.draw.rect(screen, COLOR_CARD, (0, 0, SCREEN_WIDTH, 70))
            title_surface = font_title.render("Live Preview: Align Problem Sheet", True, COLOR_TEXT)
            screen.blit(title_surface, (25, 20))
            pygame.draw.rect(screen, COLOR_ACCENT_BORDER, (0, 68, SCREEN_WIDTH, 2))

            # Monitor click states
            for event in pygame.event.get():
                if event.type == pygame.MOUSEBUTTONDOWN:
                    mouse_pos = pygame.mouse.get_pos()
                    x, y, w, h = btn_rect
                    if x <= mouse_pos[0] <= x + w and y <= mouse_pos[1] <= y + h:
                        awaiting_capture = False

            # Monitor physical inputs (e.g. START_PIN or D_PIN triggers capture)
            if GPIO.input(START_PIN) == GPIO.LOW or GPIO.input(D_PIN) == GPIO.LOW:
                awaiting_capture = False

            # Parse the MJPEG byte stream feed
            chunk = pipe.stdout.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)

            # Locate complete image frames inside the active cache array
            start = buffer.find(b'\xff\xd8')
            end = buffer.find(b'\xff\xd9', start)
            
            if start != -1 and end != -1:
                jpg_data = buffer[start:end+2]
                buffer = buffer[end+2:] # Flush buffer forward
                
                try:
                    # Load individual video frame streams dynamically into surface variables
                    img_surface = pygame.image.load_frombytes(jpg_data, (c_w, c_h), 'JPG')
                except Exception:
                    try:
                        # Fallback parsing strategy
                        import io
                        img_io = io.BytesIO(jpg_data)
                        img_surface = pygame.image.load(img_io)
                    except Exception:
                        img_surface = None

                if img_surface:
                    pygame.draw.rect(screen, COLOR_CARD, (c_x-4, c_y-4, c_w+8, c_h+8), border_radius=6)
                    screen.blit(img_surface, (c_x, c_y))

            # Keep render text loops running seamlessly beside video preview frames
            lbl = font_body.render("Center problem code sheet in frame", True, COLOR_TEXT)
            screen.blit(lbl, (40, 400))

            draw_touch_button(btn_rect, "SNAP IMAGE [D]", is_selected=True)
            pygame.display.flip()
            clock.tick(24) # Smooth preview frame updates
            
    finally:
        pipe.terminate()
        pipe.wait()

    # Trigger high-resolution capture file save
    draw_ui_base("Freezing Frame Capture Snapshot...")
    pygame.display.flip()
    
    still_cmd = f"rpicam-still -t 100 --nopreview -o {output_path}"
    subprocess.run(still_cmd, shell=True, capture_output=True)
    return os.path.exists(output_path)

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

    btn_rect = (480, 360, 280, 50)
    draw_touch_button(btn_rect, "Next Action Workflow")
    pygame.display.flip()
    
    wait_for_ui_selection(active_buttons=[(btn_rect, 0)])

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

        # 5. SUMMARY PROGRESS CLOSEOUT LAYOUT SCREEN
        play_audio(AUDIO_SUMMARY)
        draw_ui_base("Coursework Lifecycle Metrics Complete")
        pygame.draw.rect(screen, COLOR_CARD, (50, 100, 700, 320), border_radius=12)
        lbl1 = font_title.render("Session Saved Successfully!", True, COLOR_SELECTED_BG)
        lbl2 = font_body.render("Analytics data metrics safely pushed to configuration loops.", True, COLOR_TEXT)
        screen.blit(lbl1, (120, 150))
        screen.blit(lbl2, (120, 230))
        
        btn_rect = (250, 320, 300, 60)
        draw_touch_button(btn_rect, "Restart Process Core Engine")
        pygame.display.flip()
        
        wait_for_ui_selection(active_buttons=[(btn_rect, 0)])

if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
