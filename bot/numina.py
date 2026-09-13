# -*- coding: utf-8 -*-

import os
import subprocess
import sys
import time

import pygame
import RPi.GPIO as GPIO
from luma.core.interface.serial import noop, spi
from luma.core.render import canvas
from luma.led_matrix.device import max7219

# ============================================================================== 
# 1. HARDWARE HARD-CODED PIN ASSIGNMENTS (MATCHING INTEGRATION SPEC)
# ==============================================================================
START_PIN = 27   # Physical Pin 13
ESTOP_PIN = 22   # Physical Pin 15
UP_PIN = 23      # Physical Pin 16
DOWN_PIN = 24    # Physical Pin 18
LEFT_PIN = 25    # Physical Pin 22
RIGHT_PIN = 26   # Physical Pin 37

LED_GREEN = 6    # Physical Pin 31 (Idle/Ready Status)
LED_YELLOW = 13  # Physical Pin 33 (Processing/Working Status)
LED_RED = 19     # Physical Pin 35 (Error/Emergency Shutdown)

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

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Configure input keys with internal active pull-up networks
    for pin in [START_PIN, ESTOP_PIN, UP_PIN, DOWN_PIN, LEFT_PIN, RIGHT_PIN]:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Configure telemetry alert status indicators
    for pin in [LED_GREEN, LED_YELLOW, LED_RED]:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    # Register emergency-stop interrupt only after GPIO is configured.
    GPIO.add_event_detect(ESTOP_PIN, GPIO.FALLING, callback=emergency_stop_callback, bouncetime=200)

    # Initialize asynchronous sound card audio mixers
    try:
        pygame.mixer.init()
    except Exception as e:
        print(f"[WARN] Audio card initialization deferred: {e}")

    # Initialize the SPI interface layer for the MAX7219 matrix display
    try:
        serial_spi = spi(port=0, device=0, gpio=noop())
        device_matrix = max7219(serial_spi, cascaded=1)
        device_matrix.contrast(30)  # Set modest brightness value to limit current spikes
    except Exception as e:
        print(f"[WARN] SPI MAX7219 Array initialization skipped: {e}")


def set_status(state):
    """Updates physical LED indicators to showcase system operational context."""
    GPIO.output(LED_GREEN, GPIO.HIGH if state == "idle" else GPIO.LOW)
    GPIO.output(LED_YELLOW, GPIO.HIGH if state == "processing" else GPIO.LOW)
    GPIO.output(LED_RED, GPIO.HIGH if state == "error" else GPIO.LOW)


def draw_matrix_glyph(glyph_type):
    """Renders basic feedback expressions directly to the 8x8 matrix panel."""
    global device_matrix

    if device_matrix is None:
        return

    with canvas(device_matrix) as draw:
        if glyph_type == "smile":
            # Draw basic smiling face bounding coordinate dots
            draw.point((1, 2), fill="white")
            draw.point((1, 5), fill="white")
            draw.point((4, 1), fill="white")
            draw.point((5, 2), fill="white")
            draw.point((5, 3), fill="white")
            draw.point((5, 4), fill="white")
            draw.point((5, 5), fill="white")
            draw.point((4, 6), fill="white")
        elif glyph_type == "arrow_right":
            # Draw standard menu step progression navigation arrow
            for x in range(2, 6):
                draw.point((3, x), fill="white")
            draw.point((2, 4), fill="white")
            draw.point((4, 5), fill="white")
        elif glyph_type == "clear":
            device_matrix.clear()


def emergency_stop_callback(channel):
    """High-priority hardware interrupt callback loop ensuring absolute mechanical safety."""
    set_status("error")
    print("\n[🚨 EMERGENCY SHUTDOWN TRIGGERED] Immediately killing active processes...")

    # 1. Neutralize audio playback pipelines instantly
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass

    # 2. Kill hardware-accelerated video display instances completely
    os.system("pkill vlc || pkill cvlc")

    # 3. Clean up display matrices and baseline pins
    try:
        if device_matrix:
            device_matrix.clear()
    except Exception:
        pass

    GPIO.cleanup()
    print("[SYSTEM] Output pin layers neutralized successfully. Program execution halted.")
    sys.exit(0)


# ============================================================================== 
# 4. ROBUST DEBOUNCED PIN SAMPLING LOGIC
# ==============================================================================
def wait_for_press(target_pins, debounce_ms=20):
    """Blocks active thread loop until a valid, debounced active-low press is seen."""
    while True:
        for pin in target_pins:
            if GPIO.input(pin) == GPIO.LOW:
                time.sleep(debounce_ms / 1000.0)
                if GPIO.input(pin) == GPIO.LOW:
                    # Hold processing thread until the finger clears the switch contact pad
                    while GPIO.input(pin) == GPIO.LOW:
                        time.sleep(0.01)
                    return pin
        time.sleep(0.02)


def select_grade():
    """Menu loop for selecting a grade using UP/DOWN and START as confirm."""
    selected_grade = 9
    print(f" -> Active Highlight Profile: Grade {selected_grade}")

    while True:
        key = wait_for_press([UP_PIN, DOWN_PIN, START_PIN])
        if key == UP_PIN and selected_grade < 12:
            selected_grade += 1
            print(f" -> Active Highlight Profile: Grade {selected_grade}")
        elif key == DOWN_PIN and selected_grade > 9:
            selected_grade -= 1
            print(f" -> Active Highlight Profile: Grade {selected_grade}")
        elif key == START_PIN:
            print(f"[OK] Grade verification confirmed: Grade {selected_grade}")
            return selected_grade


def select_option(options, label):
    """Generic left/right menu selector with START as confirm."""
    current_idx = 0
    print(f" -> {label}: {options[current_idx]}")

    while True:
        key = wait_for_press([LEFT_PIN, RIGHT_PIN, START_PIN])
        if key == RIGHT_PIN:
            current_idx = (current_idx + 1) % len(options)
            print(f" -> {label}: {options[current_idx]}")
        elif key == LEFT_PIN:
            current_idx = (current_idx - 1) % len(options)
            print(f" -> {label}: {options[current_idx]}")
        elif key == START_PIN:
            print(f"[OK] {label} confirmed: {options[current_idx]}")
            return options[current_idx]


# ============================================================================== 
# 5. MULTIMEDIA DEVICE DRIVER OVERLAYS
# ==============================================================================
def play_audio(file_path):
    if not os.path.exists(file_path):
        print(f"[AUDIO EMULATOR] Mock play active for asset: {os.path.basename(file_path)}")
        time.sleep(2.5)
        return

    try:
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"[AUDIO ERROR] Playback error seen: {e}")


def play_video(file_path):
    if not os.path.exists(file_path):
        print("[VIDEO EMULATOR] Mock video rendering display on monitor console...")
        time.sleep(3.0)
        return

    print(f"[VIDEO RUNNING] Streaming visual assets to screen: {file_path}")
    # Force VLC to boot in full-screen environment layer and self-terminate upon end
    cmd = f"cvlc --no-osd --fullscreen --play-and-exit {file_path} > /dev/null 2>&1"
    subprocess.Popen(cmd, shell=True)


def execute_camera_capture(output_path):
    print("[CAMERA MODULE 3] Running autofocus calibration capture routine...")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Target explicit single shot resolution values using clean libcamera architecture commands
    cmd = f"libcamera-still -t 1500 --autofocus-mode normal -o {output_path} --nopreview"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.returncode == 0 and os.path.exists(output_path)


# ============================================================================== 
# 6. INTEGRATED FLOW MANAGER (FIGURE 14 ARCHITECTURE ENGINE)
# ==============================================================================
def run_numina_engine():
    setup_hardware()
    print("======================================================")
    print(" NUMINA BOT OPERATIONAL CORE: REVISION INTERACTION   ")
    print("======================================================")

    while True:
        # F1.0 / F2.0: standby and startup ready state
        set_status("idle")
        draw_matrix_glyph("clear")
        print("\n[STANDBY F1.0] Awaiting user initialization signal via START switch...")
        wait_for_press([START_PIN])

        # F3.0: intro and onboarding
        set_status("processing")
        draw_matrix_glyph("smile")
        print("[ONBOARDING F3.0] Executing digital audio intro audio framework...")
        play_audio(AUDIO_INTRO)

        # F4.0: select grade
        print("[CONFIG F4.0] Select target study grade (Grade 9 through Grade 12).")
        selected_grade = select_grade()

        # F5.0: select topic
        print("[CONFIG F5.0] Select educational domain concept block. Press START to save.")
        concept_array = ["Linear Algebra", "Geometry Proofs", "Physics Dynamics", "Chemistry Moles"]
        selected_concept = select_option(concept_array, "Current Domain Selection")
        print(f"[OK] Concept parameter configured successfully: {selected_concept}")

        # F6.0: select lesson vs problem path
        print("[ROUTING F6.0] Select Mode: [UP Key] Lesson Package | [DOWN Key] Problem Matrix Solver")
        mode_branch = wait_for_press([UP_PIN, DOWN_PIN])

        if mode_branch == UP_PIN:
            # Lesson pathway: F7.0 -> F10.0
            print("[TRACK A] Deploying structured curriculum package F7.0...")
            print("[MEDIA F8.0] Syncing video stream visuals with microphone audio instructions...")
            play_video(VIDEO_LESSON)
            play_audio(AUDIO_GUIDE)

            print("[EVALUATION F9.0] Pushing verification checklist challenge block...")
            print(" -> Interact to complete assessment quiz challenge: [UP for True | DOWN for False]")
            quiz_answer = wait_for_press([UP_PIN, DOWN_PIN])
            if quiz_answer == UP_PIN:
                print("[CHECK F9.1] Student answered correctly. Moving to concept reinforcement.")
            else:
                print("[CHECK F9.2] Student answered incorrectly. Revising the concept with guided audio.")
                play_audio(AUDIO_GUIDE)

            print("[FACT OUTPUT F10.0] Directing real-world applications summary context block...")
            play_audio(AUDIO_FACT)

        else:
            # Problem pathway: F11.0 -> F14.0
            print("[TRACK B] Deploying analytical scanner processor pipeline F11.0...")
            print(" -> Choose Input Source: [LEFT Key] Capture Camera Module | [RIGHT Key] Sample Storage")
            capture_mode = wait_for_press([LEFT_PIN, RIGHT_PIN])

            if capture_mode == LEFT_PIN:
                print("[HARDWARE F11.1] Capturing workspace frame via CSI lens layout...")
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
            print(" -> [Control Interaction] Tap RIGHT button to progress workflow...")
            wait_for_press([RIGHT_PIN])

            print("[CHECK F14.0] Verifying understanding matrix parameters. [UP for understood | DOWN for confused]")
            understanding = wait_for_press([UP_PIN, DOWN_PIN])
            if understanding == UP_PIN:
                print("[CHECK F14.1] Learner confirmed understanding. Continue with summary.")
            else:
                print("[CHECK F14.2] Learner is still confused. Re-loop through guided explanation.")
                play_audio(AUDIO_GUIDE)

        # F15.0 -> F17.0: summary and repeat/exit decision
        print("[SUMMARY F15.0] Broadcasting logged classroom progress analytics metrics...")
        play_audio(AUDIO_SUMMARY)
        print("[PROMPT F16.0] 'Do you want to address alternative coursework sections?'")
        print(" -> Action Vector: [UP Button for YES, Return to Loop] | [DOWN Button for NO, Shut Down]")
        loop_decision = wait_for_press([UP_PIN, DOWN_PIN])

        if loop_decision == DOWN_PIN:
            print("[DEEP SLEEP F17.0] Isolating system pins. Powering down safe core registers.")
            break

        draw_matrix_glyph("clear")
        GPIO.cleanup()
        print("[TERMINATE COMPLETE] System architecture parked safely.")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in [START_PIN, ESTOP_PIN, UP_PIN, DOWN_PIN, LEFT_PIN, RIGHT_PIN]:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        for pin in [LED_GREEN, LED_YELLOW, LED_RED]:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        GPIO.add_event_detect(ESTOP_PIN, GPIO.FALLING, callback=emergency_stop_callback, bouncetime=200)
        print("[LOOP F17.1] Ready for the next learner session.")


if __name__ == "__main__":
    try:
        run_numina_engine()
    except KeyboardInterrupt:
        GPIO.cleanup()

