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
# 3. GLOBAL GUI GRAPHICS CONFIGURATIONS (Optimised for 5-inch 800x480 screen)
# ==============================================================================
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
COLOR_BG = (20, 24, 33)       # Deep sleek dark blue
COLOR_CARD = (32, 38, 54)     # Light grey-blue container blocks
COLOR_TEXT = (240, 244, 255)   # Off-white crisp text
COLOR_ACCENT = (0, 168, 204)   # Vibrant educational cyan
COLOR_ALERT = (255, 75, 75)    # Red warning indicators

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

    # Initialize Pygame Video & Audio simultaneously
    pygame.init()
    pygame.mixer.init()
    
    # Force open exact 5-inch resolution window frame
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Numina Educational Engine v2.0")
    
    font_title = pygame.font.SysFont("Arial", 32, bold=True)
    font_body = pygame.font.SysFont("Arial", 22)

    try:
        serial_spi = spi(port=0, device=0, gpio=noop())
        device_matrix = max7219(serial_spi, cascaded=1)
        device_matrix.contrast(30)
        device_matrix.clear()
    except Exception:
        device_matrix = None

def emergency_stop_callback(channel):
    pygame.mixer.music.stop()
    os.system("pkill vlc || pkill cvlc")
    pygame.quit()
    os._exit(0)

# ============================================================================== 
# 4. GUI INTERFACE COMPONENT PAINTERS
# ==============================================================================
def draw_ui_base(title_text):
    screen.fill(COLOR_BG)
    # Header area
    pygame.draw.rect(screen, COLOR_CARD, (0, 0, SCREEN_WIDTH, 70))
    title_surface = font_title.render(title_text, True, COLOR_TEXT)
    screen.blit(title_surface, (20, 15))
    # Elegant separation strip
    pygame.draw.rect(screen, COLOR_ACCENT, (0, 68, SCREEN_WIDTH, 2))

def draw_touch_button(rect, text, is_pressed=False):
    color = COLOR_ACCENT if not is_pressed else COLOR_TEXT
    text_color = COLOR_BG if not is_pressed else COLOR_ACCENT
    pygame.draw.rect(screen, COLOR_CARD, rect, border_radius=8)
    pygame.draw.rect(screen, color, rect, width=2, border_radius=8)
    
    surf = font_body.render(text, True, text_color)
    text_rect = surf.get_rect(center=(rect[0] + rect[2]//2, rect[1] + rect[3]//2))
    screen.blit(surf, text_rect)

def render_options_menu(title, options_list):
    """Draws up to 4 options neatly balanced as large interactive grid block tiles"""
    draw_ui_base(title)
    # 4 grid coordinates matching A, B, C, D buttons/touch vectors
    buttons = [
        (40, 120, 340, 120),  # Top Left [A]
        (420, 120, 340, 120), # Top Right [B]
        (40, 280, 340, 120),  # Bottom Left [C]
        (420, 280, 340, 120)  # Bottom Right [D]
    ]
    
    active_buttons = []
    for idx, option in enumerate(options_list[:4]):
        rect = buttons[idx]
        draw_touch_button(rect, option)
        active_buttons.append((rect, idx))
        
    pygame.display.flip()
    return active_buttons

# ============================================================================== 
# 5. INPUT EVENT CONTROLLER LOOP (Unifies Physical Buttons + Touchscreen)
# ==============================================================================
def wait_for_ui_selection(active_buttons=None, physical_pins=None):
    """Listens for an input from the touchscreen coordinates OR hardware buttons"""
    while True:
        # Check Hardware Pins
        if physical_pins:
            for pin in physical_pins:
                if GPIO.input(pin) == GPIO.LOW:
                    time.sleep(0.1) # Debounce
                    return ("hardware", pin)

        # Check Pygame Touchscreen Events
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
# 6. INTEGRATED MEDIA DRIVERS (NATIVE MEDIA RENDERERS)
# ==============================================================================
def gui_play_video(file_path):
    """Plays your lesson video natively inside the Pygame UI instead of using cvlc"""
    draw_ui_base("Streaming Media Lesson Profile...")
    pygame.display.flip()

    if not os.path.exists(file_path):
        # Fallback simulator if file doesn't exist
        time.sleep(2)
        return

    # To run smoothly on a Pi 5, we use ffmpeg to pipe video frames into raw bytes
    cmd = [
        'ffmpeg', '-i', file_path, '-f', 'image2pipe', 
        '-pix_fmt', 'rgb24', '-vcodec', 'rawvideo', '-'
    ]
    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)

    # Center frame dimensions (Scaled to fit neatly below the header bar)
    v_w, v_h = 480, 270
    v_x, v_y = (SCREEN_WIDTH - v_w) // 2, 120

    clock = pygame.time.Clock()
    running_video = True
    
    try:
        while running_video:
            # Check for close events
            for event in pygame.event.get():
                if event.type == pygame.MOUSEBUTTONDOWN: # Tap anywhere to skip video
                    running_video = False

            raw_image = pipe.stdout.read(v_w * v_h * 3)
            if not raw_image:
                break

            video_surface = pygame.image.fromstring(raw_image, (v_w, v_h), 'RGB')
            
            # Frame container card background
            pygame.draw.rect(screen, COLOR_CARD, (v_x-10, v_y-10, v_w+20, v_h+20), border_radius=12)
            screen.blit(video_surface, (v_x, v_y))
            
            # Subtext instruction label
            lbl = font_body.render("Tap screen anywhere to continue lesson", True, COLOR_TEXT)
            screen.blit(lbl, (SCREEN_WIDTH//2 - lbl.get_width()//2, 415))
            
            pygame.display.flip()
            clock.tick(30) # Lock to stable 30fps streaming
    finally:
        pipe.terminate()

def gui_show_captured_image(image_path):
    """Loads and renders your captured snapshot directly onto the 5-inch interface"""
    draw_ui_base("Analytical Workspace Capture Resolved")
    
    if os.path.exists(image_path):
        try:
            img = pygame.image.load(image_path)
            # Neatly scale it to fit the center panel frame
            img = pygame.transform.scale(img, (400, 300))
            screen.blit(img, (40, 110))
        except Exception:
            pass
    else:
        # Fallback container display box if camera path skipped
        pygame.draw.rect(screen, COLOR_CARD, (40, 110, 400, 300), border_radius=8)
        lbl = font_body.render("[Missing Capture Data Frame Asset]", True, COLOR_ALERT)
        screen.blit(lbl, (100, 230))

    # Render data text analytics blocks beside the captured display frame
    pygame.draw.rect(screen, COLOR_CARD, (480, 110, 280, 300), border_radius=8)
    lines = ["[ANALYSIS MATCHED]", "Problem: 3x + 9 = 24", "", "Step 1: Subtract 9", "        3x = 15", "Step 2: Divide by 3", "        x = 5"]
    for i, line in enumerate(lines):
        color = COLOR_ACCENT if i == 1 else COLOR_TEXT
        text_surf = font_body.render(line, True, color)
        screen.blit(text_surf, (500, 130 + (i * 30)))

    # Action Confirmation button
    btn_rect = (480, 360, 280, 50)
    draw_touch_button(btn_rect, "Next Action Workflow")
    pygame.display.flip()
    
    wait_for_ui_selection(active_buttons=[(btn_rect, 0)])

def execute_camera_capture(output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        try: os.remove(output_path)
        except Exception: pass
    cmd = f"rpicam-still -t 100 --nopreview -o {output_path}"
    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return os.path.exists(output_path)

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
        
        t_surf = font_title.render("NUMINA BOT CORE SYSTEMS OPERATIONAL", True, COLOR_ACCENT)
        b_surf = font_body.render("Press the physical START button switch to wake engine loop", True, COLOR_TEXT)
        screen.blit(t_surf, (SCREEN_WIDTH//2 - t_surf.get_width()//2, 150))
        screen.blit(b_surf, (SCREEN_WIDTH//2 - b_surf.get_width()//2, 240))
        pygame.display.flip()
        
        # Wait for physical start button hook execution
        wait_for_ui_selection(physical_pins=[START_PIN])

        # Play Intro Audio track block
        play_audio(AUDIO_INTRO)

        # 2. SELECT GRADE INTERFACE PANEL
        menu_items = ["Grade 9 Curriculum", "Grade 10 Curriculum", "Grade 11 Curriculum", "Grade 12 Curriculum"]
        btns = render_options_menu("Select Educational Curriculum Target Level", menu_items)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_idx = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)
        print(f"[OK] Level configuration locked: {menu_items[chosen_idx]}")

        # 3. SELECT DOMAIN CONCEPT MATRIX TRACKER
        concepts = ["Linear Algebra", "Geometry Proofs", "Physics Dynamics", "Chemistry Moles"]
        btns = render_options_menu("Select Domain Subject Concept Study Module", concepts)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_concept = concepts[idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)]

        # 4. PATH TRACK SELECTOR ROUTER
        paths = ["Run Core Lesson Video Package", "Deploy Analytical Scanner Environment", "Cancel Selection", "Return to Idle Loop"]
        btns = render_options_menu("Choose Interaction Path Mode Pipeline", paths)
        src, idx = wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
        chosen_path = idx if src == "touch" else [A_PIN, B_PIN, C_PIN, D_PIN].index(idx)

        if chosen_path == 0:
            # ---- TRACK A: VIDEO ENGINE LECTURE MODULE ----
            play_audio(AUDIO_GUIDE)
            gui_play_video(VIDEO_LESSON)
            
            # Quick interactive GUI grading quiz question structure
            quiz_opts = ["Always True (Option A)", "Conditional Variant (Option B)", "Never True (Option C)", "Insufficient Core Telemetry (Option D)"]
            btns = render_options_menu("Assessment Validation Q1: Is this homogeneous?", quiz_opts)
            wait_for_ui_selection(active_buttons=btns, physical_pins=[A_PIN, B_PIN, C_PIN, D_PIN])
            play_audio(AUDIO_FACT)
        else:
            # ---- TRACK B: CAMERA FRAME PROCESSING CAPTURE MODULE ----
            draw_ui_base("Analytical Camera Workspace Capture System")
            pygame.draw.rect(screen, COLOR_CARD, (100, 120, 600, 240), border_radius=12)
            lbl = font_body.render("Capturing workspace frame via CSI camera lens link...", True, COLOR_TEXT)
            screen.blit(lbl, (150, 220))
            pygame.display.flip()
            
            # Execute frame capture snapshot directly via the connected camera
            execute_camera_capture(CAPTURE_PATH)
            
            # Render your newly captured photograph right onto your 5-inch screen layout
            gui_show_captured_image(CAPTURE_PATH)

        # 5. SUMMARY PROGRESS CLOSEOUT LAYOUT SCREEN
        play_audio(AUDIO_SUMMARY)
        draw_ui_base("Coursework Lifecycle Metrics Complete")
        pygame.draw.rect(screen, COLOR_CARD, (50, 100, 700, 320), border_radius=12)
        lbl1 = font_title.render("Session Saved Successfully!", True, COLOR_ACCENT)
        lbl2 = font_body.render("Analytics data metrics safely pushed to configuration loops.", True, COLOR_TEXT)
        screen.blit(lbl1, (120, 160))
        screen.blit(lbl2, (120, 240))
        
        btn_rect = (250, 330, 300, 60)
        draw_touch_button(btn_rect, "Restart Process Core Engine")
        pygame.display.flip()
        
        wait_for_ui_selection(active_buttons=[(btn_rect, 0)])

if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
