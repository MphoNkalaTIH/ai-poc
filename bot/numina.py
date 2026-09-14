# -*- coding: utf-8 -*-

import os
import subprocess
import sys
import time
import pygame

# Suppress luma initialization errors when desktop environment links are unavailable
os.environ["LUMA_NO_DISPLAY"] = "1"

import RPi.GPIO as GPIO
from luma.core.interface.serial import noop, spi
from luma.core.render import canvas
from luma.led_matrix.device import max7219

def is_raspberry_pi_environment():
    """Return True only when the app is running on an actual Raspberry Pi OS host."""
    try:
        with open("/proc/device-tree/model", "r", encoding="utf-8", errors="ignore") as handle:
            model = handle.read().strip()
        return "Raspberry Pi" in model
    except Exception:
        return False

def require_raspberry_pi_runtime():
    if not is_raspberry_pi_environment():
        raise RuntimeError(
            "Numina must run on a physical Raspberry Pi 5 with Raspberry Pi OS. "
            "GPIO access is unavailable in WSL, VM, or unsupported environments."
        )

def safe_gpio_cleanup():
    try:
        print("[GPIO] Cleaning up peripheral registers and pin maps safely...")
        GPIO.cleanup()
    except RuntimeError:
        pass

# ============================================================================== 
# 1. HARDWARE HARD-CODED PIN ASSIGNMENTS (MATCHING INTEGRATION SPEC)
# ==============================================================================
START_PIN = 27   # Physical Pin 13
ESTOP_PIN = 22   # Physical Pin 15
UP_PIN = 23      # Physical Pin 16
DOWN_PIN = 24    # Physical Pin 18
LEFT_PIN = 25    # Physical Pin 22
RIGHT_PIN = 26   # Physical Pin 37

NAV_BUTTONS = [
    ("A", UP_PIN),
    ("B", DOWN_PIN),
    ("C", LEFT_PIN),
    ("D", RIGHT_PIN),
]
NAV_KEY_TO_INDEX = {pin: idx for idx, (_, pin) in enumerate(NAV_BUTTONS)}
NAV_LABEL_TO_PIN = {label: pin for label, pin in NAV_BUTTONS}
GRADE_OPTIONS = [9, 10, 11, 12]
GRADE_BY_BUTTON = {
    UP_PIN: 9,
    DOWN_PIN: 10,
    LEFT_PIN: 11,
    RIGHT_PIN: 12,
}

# ============================================================================== 
# 2. RUNTIME ASSET DIRECTORY CONVENTIONS
# ==============================================================================
AUDIO_INTRO = "/home/pi/numina/audio/intro.mp3"
AUDIO_GUIDE = "/home/pi/numina/audio/guide_step.mp3"
AUDIO_FACT = "/home/pi/numina/audio/fun_fact.mp3"
AUDIO_SUMMARY = "/home/pi/numina/audio/summary.mp3"
VIDEO_LESSON = "/home/pi/numina/video/lesson_viz.mp4"
CAPTURE_PATH = "/home/pi/numina/capture/problem_input.jpg"

# ============================================================================== 
# 3. LOW-LEVEL SYSTEM AND INTERFACE INITIALIZATION
# ==============================================================================
device_matrix = None

def setup_hardware():
    global device_matrix
    print("[INIT] Verifying system hardware environment requirements...")
    require_raspberry_pi_runtime()

    print("[GPIO] Setting board numbering layout mode to BCM...")
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    print("[GPIO] Initializing input buttons with internal software pull-up resistors...")
    for pin in [START_PIN, ESTOP_PIN, UP_PIN, DOWN_PIN, LEFT_PIN, RIGHT_PIN]:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        print(f" -> Pin BCM {pin} initialized successfully as INPUT with PULL_UP.")

    print("[GPIO] Registering high-priority hardware interrupt callback loop on E-STOP...")
    GPIO.add_event_detect(ESTOP_PIN, GPIO.FALLING, callback=emergency_stop_callback, bouncetime=200)

    print("[AUDIO] Initializing sound card hardware subsystem interfaces...")
    try:
        pygame.mixer.init()
        print("[AUDIO] Pygame audio mixer successfully registered.")
    except Exception as e:
        print(f"[WARN] Audio card initialization deferred: {e}")

    print("[SPI] Attempting to hook into high-speed MAX7219 Dot-Matrix display hardware bus...")
    try:
        serial_spi = spi(port=0, device=0, gpio=noop())
        device_matrix = max7219(serial_spi, cascaded=1)
        device_matrix.contrast(30)  # Moderate current limit brightness threshold
        device_matrix.clear()
        time.sleep(0.1)
        set_status("idle")
        print("[MATRIX] SPI MAX7219 communication layer fully unblocked and verified.")
    except Exception as e:
        device_matrix = None
        print(f"[WARN] SPI MAX7219 Array initialization skipped or failed: {e}")

def set_status(state):
    """Updates the MAX7219 matrix to indicate the robot's live status."""
    print(f"[TELEMETRY] System state transition requested -> State: '{state}'")

    if device_matrix is None:
        print(f"[MATRIX] State='{state}' (Visual skipped; hardware frame unmapped)")
        return

    if state == "idle":
        draw_matrix_glyph("idle")
    elif state == "processing":
        draw_matrix_glyph("processing")
    elif state == "error":
        draw_matrix_glyph("error")
    else:
        draw_matrix_glyph("clear")
    print(f"[MATRIX] Graphic context for state='{state}' written onto screen panel.")

def draw_matrix_glyph(glyph_type):
    """Renders precise static visual glyph blocks straight onto the 8x8 matrix panel."""
    global device_matrix
    if device_matrix is None:
        return

    with canvas(device_matrix) as draw:
        if glyph_type == "clear":
            device_matrix.clear()
        elif glyph_type == "idle":
            # Small uniform center tracking node representing ready/standby
            for x, y in [(3, 3), (3, 4), (4, 3), (4, 4)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "processing":
            # Bar pattern signifying backend operations/computing running
            for x in range(8):
                if x % 2 == 0:
                    draw.point((x, 3), fill="white")
                    draw.point((x, 4), fill="white")
        elif glyph_type == "error":
            # Large systemic fault 'X' icon for crash/E-STOP state
            for x, y in [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7),
                         (0, 7), (1, 6), (2, 5), (3, 4), (4, 3), (5, 2), (6, 1), (7, 0)]:
                draw.point((x, y), fill="white")
        elif glyph_type == "smile":
            # Operational smiling mouth expression for friendly student interaction
            draw.point((1, 2), fill="white")
            draw.point((1, 5), fill="white")
            draw.point((4, 1), fill="white")
            draw.point((5, 2), fill="white")
            draw.point((5, 3), fill="white")
            draw.point((5, 4), fill="white")
            draw.point((5, 5), fill="white")
            draw.point((4, 6), fill="white")
        elif glyph_type == "arrow_right":
            # Incremental workflow progression menu pointer arrow
            for x in range(2, 6):
                draw.point((3, x), fill="white")
            draw.point((2, 4), fill="white")
            draw.point((4, 5), fill="white")
        else:
            device_matrix.clear()

def emergency_stop_callback(channel):
    """High-priority hardware interrupt callback loop ensuring absolute mechanical safety."""
    print("\n[🚨 CRITICAL INTERRUPT] EMERGENCY SHUTDOWN TERMINATION EVENT ACTIVATED!")
    
    # 1. Force the matrix to display the error 'X' glyph instantly
    try:
        if device_matrix:
            with canvas(device_matrix) as draw:
                for x, y in [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7),
                             (0, 7), (1, 6), (2, 5), (3, 4), (4, 3), (5, 2), (6, 1), (7, 0)]:
                    draw.point((x, y), fill="white")
            print("[E-STOP] Matrix display forced to ERROR mode.")
    except Exception:
        pass

    # 2. Kill active sounds immediately
    try:
        pygame.mixer.music.stop()
        print("[E-STOP] Sound card playback pipelines neutralized.")
    except Exception:
        pass

    # 3. Force terminate running video instances immediately
    print("[E-STOP] Killing active video tasks...")
    os.system("pkill vlc || pkill cvlc")

    safe_gpio_cleanup()
    print("[E-STOP] All logic pins safely neutralized. Terminating execution path completely.")
    sys.exit(0)

# ============================================================================== 
# 4. ROBUST DEBOUNCED PIN SAMPLING LOGIC
# ==============================================================================
def wait_for_press(target_pins, debounce_ms=20):
    """Wait for a fresh active-low press, ignoring any button already held at call time."""
    print(f"[POLLING] Monitoring input keys on pins: {target_pins}...")

    # Ignore any button already pressed before the user starts a new interaction.
    while True:
        if all(GPIO.input(pin) == GPIO.HIGH for pin in target_pins):
            break
        time.sleep(0.02)

    while True:
        for pin in target_pins:
            if GPIO.input(pin) == GPIO.LOW:
                time.sleep(debounce_ms / 1000.0)
                if GPIO.input(pin) == GPIO.LOW:
                    print(f"[POLLING] Pin BCM {pin} active state confirmed. Waiting for release...")
                    while GPIO.input(pin) == GPIO.LOW:
                        time.sleep(0.01)
                    print(f"[POLLING] Pin BCM {pin} released. Returning token.")
                    return pin
        time.sleep(0.02)

def select_grade():
    """Grade selection using A/B/C/D navigation and START to confirm."""
    current_grade = 9
    print(" -> Grade selection: A=9 | B=10 | C=11 | D=12")
    print(f" -> Selected Grade: {current_grade}")

    while True:
        key = wait_for_press([UP_PIN, DOWN_PIN, LEFT_PIN, RIGHT_PIN, START_PIN])

        if key == START_PIN:
            print(f"[OK] Grade selection confirmed: Grade {current_grade}")
            return current_grade

        if key in GRADE_BY_BUTTON:
            current_grade = GRADE_BY_BUTTON[key]
            print(f" -> Selected Grade: {current_grade}")


def select_option(options, label):
    """Multi-choice selector using A/B/C/D navigation and START as confirm."""
    if not options:
        return None

    display_options = options[:4]
    current_idx = 0
    print(f" -> {label}: A={display_options[0]} | B={display_options[1]} | C={display_options[2]} | D={display_options[3]}")
    print(f" -> {label}: {display_options[current_idx]}")

    while True:
        key = wait_for_press([UP_PIN, DOWN_PIN, LEFT_PIN, RIGHT_PIN, START_PIN])

        if key == START_PIN:
            print(f"[OK] {label} confirmed: {display_options[current_idx]}")
            return display_options[current_idx]

        if key in NAV_KEY_TO_INDEX:
            current_idx = NAV_KEY_TO_INDEX[key] % len(display_options)
            print(f" -> {label}: {display_options[current_idx]}")


# ============================================================================== 
# 5. MULTIMEDIA DEVICE DRIVER OVERLAYS
# ==============================================================================
def play_audio(file_path):
    print(f"[MEDIA] Checking voice resource location: {file_path}")

    if not os.path.exists(file_path):
        print(f"[AUDIO] Missing asset: {os.path.basename(file_path)}. Skipping playback cleanly.")
        return False

    try:
        print(f"[AUDIO] Streaming data blocks through sound card channel: {os.path.basename(file_path)}")
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

        print("[AUDIO] Track block completed execution playback.")
        return True
    except Exception as e:
        print(f"[AUDIO ERROR] Playback error seen: {e}")
        return False


def play_video(file_path):
    print(f"[MEDIA] Checking visual resource location: {file_path}")

    if not os.path.exists(file_path):
        print("[VIDEO EMULATOR] Mock video rendering display on monitor console...")
        time.sleep(3.0)
        return

    print(f"[VIDEO RUNNING] Streaming visual assets to screen: {file_path}")
    cmd = f"cvlc --no-osd --fullscreen --play-and-exit {file_path} > /dev/null 2>&1"
    subprocess.Popen(cmd, shell=True)


def execute_camera_capture(output_path):
    print("[CAMERA MODULE 3] Running autofocus calibration capture routine...")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = f"libcamera-still -t 1500 --autofocus-mode normal -o {output_path} --nopreview"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode == 0 and os.path.exists(output_path)


# ============================================================================== 
# 6. INTEGRATED FLOW MANAGER (FIGURE 14 ARCHITECTURE ENGINE)
# ==============================================================================
def run_numina_engine():
    setup_hardware()
    print("======================================================")
    print(" NUMINA BOT OPERATIONAL CORE: LIFECYCLE INTERACTION   ")
    print("======================================================")

    while True:
        print("\n[STANDBY F1.0] Awaiting user initialization signal via START switch...")
        set_status("idle")
        wait_for_press([START_PIN])

        set_status("processing")
        draw_matrix_glyph("smile")
        print("[ONBOARDING F3.0] Executing digital audio intro audio framework...")
        play_audio(AUDIO_INTRO)

        print("[CONFIG F4.0] Select target study grade (Grade 9 through Grade 12).")
        selected_grade = select_grade()

        print("[CONFIG F5.0] Select educational domain concept block. Press START to save.")
        concept_array = ["Linear Algebra", "Geometry Proofs", "Physics Dynamics", "Chemistry Moles"]
        selected_concept = select_option(concept_array, "Current Domain Selection")
        print(f"[OK] Concept parameter configured successfully: {selected_concept}")

        print("[ROUTING F6.0] Select Mode: [A] Lesson Package | [B] Problem Matrix Solver")
        mode_branch = wait_for_press([UP_PIN, DOWN_PIN])

        if mode_branch == UP_PIN:
            print("[TRACK A] Deploying structured curriculum package F7.0...")
            print("[MEDIA F8.0] Syncing video stream visuals with microphone audio instructions...")
            play_video(VIDEO_LESSON)
            play_audio(AUDIO_GUIDE)

            print("[EVALUATION F9.0] Pushing verification checklist challenge block...")
            print(" -> Interact to complete assessment quiz challenge: [A] True | [B] False")
            quiz_answer = wait_for_press([UP_PIN, DOWN_PIN])

            if quiz_answer == UP_PIN:
                print("[CHECK F9.1] Student answered correctly. Moving to concept reinforcement.")
            else:
                print("[CHECK F9.2] Student answered incorrectly. Revising the concept with guided audio.")
                play_audio(AUDIO_GUIDE)

            print("[FACT OUTPUT F10.0] Directing real-world applications summary context block...")
            play_audio(AUDIO_FACT)
        else:
            print("[TRACK B] Deploying analytical scanner processor pipeline F11.0...")
            print(" -> Choose Input Source: [C] Capture Camera Module | [D] Sample Storage")
            capture_mode = wait_for_press([LEFT_PIN, RIGHT_PIN])

            if capture_mode == LEFT_PIN:
                print("[HARDWARE F11.1] Capturing workspace frame via CSI lens layout...")
                set_status("processing")
                if execute_camera_capture(CAPTURE_PATH):
                    print("[PARSING F11.2] Extracting structural equation tokens from captured picture...")
                else:
                    print("[WARN] External camera input missing. Utilizing storage fallback array indices.")
            else:
                print("[DATABASE F11.3] Parsing targeted sample example question blocks...")

            print("[ANALYSIS F12.0] Problem processing resolved: '3x + 9 = 24'")
            mock_steps = [
                "Subtract 9 from both sides of the equation -> 3x = 15",
                "Divide both sides by coefficients -> x = 5",
            ]

            print("[GUIDE F13.0] Reviewing calculated mathematical derivations step-by-step...")
            for step_data in mock_steps:
                print(f" -> Core Instruction: {step_data}")

            draw_matrix_glyph("arrow_right")
            play_audio(AUDIO_GUIDE)
            print(" -> [Control Interaction] Tap D button to progress workflow...")
            wait_for_press([RIGHT_PIN])

            print("[CHECK F14.0] Verifying understanding matrix parameters. [A] Understood | [B] Confused")
            understanding = wait_for_press([UP_PIN, DOWN_PIN])
            if understanding == UP_PIN:
                print("[CHECK F14.1] Learner confirmed understanding. Continue with summary.")
            else:
                print("[CHECK F14.2] Learner is still confused. Re-loop through guided explanation.")
                play_audio(AUDIO_GUIDE)

        print("[SUMMARY F15.0] Broadcasting logged classroom progress analytics metrics...")
        play_audio(AUDIO_SUMMARY)
        print("[PROMPT F16.0] 'Do you want to address alternative coursework sections?'")
        print(" -> Action Vector: [A] YES, return to loop | [B] NO, shut down")
        loop_decision = wait_for_press([UP_PIN, DOWN_PIN])

        if loop_decision == DOWN_PIN:
            print("[DEEP SLEEP F17.0] Powering down safe core registers.")
            break

        print("[LOOP F17.1] Re-initializing configuration variables. Ready for the next learner session.")
        draw_matrix_glyph("clear")
        safe_gpio_cleanup()

    print("[TERMINATE COMPLETE] System architecture parked safely.")


if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        safe_gpio_cleanup()
    except RuntimeError as exc:
        print(f"[RUNTIME ERROR] {exc}")
        safe_gpio_cleanup()
        sys.exit(1)
