
#!/bin/bash
# ==============================================================================
# NUMINA LINUX AUTOMATION DEPLOYMENT SYSTEM REGISTRATION ENGINE
# ==============================================================================
echo "⚙️ Initializing file tracking environments..."
# 1. Enforce local environment workspace project folder layouts
mkdir -p /home/pi/numina/audio
mkdir -p /home/pi/numina/video
mkdir -p /home/pi/numina/capture
for g in 9 10 11 12; do mkdir -p /home/pi/numina/maths/grade_$g; done
# Copy curriculum topic folders without overwriting media already placed on the device
[ -d maths ] && cp -rn maths/. /home/pi/numina/maths/
# 2. Install the current application entry point
cp numina.py /home/pi/numina/numina.py
chown -R pi:pi /home/pi/numina
chmod +x /home/pi/numina/numina.py
# 3. Mount service architecture scripts directly inside Linux initialization targets
echo "🚚 Injecting systemd boot launch hooks into system directories..."
sudo cp numina.service /etc/systemd/system/numina.service
sudo chmod 644 /etc/systemd/system/numina.service
# 4. Refresh background tracking system registers and lock auto startup execution on
sudo systemctl daemon-reload
sudo systemctl enable numina.service

echo "✅ Automation profile configuration successfully registered!"
echo "💡 The Numina workflow will execute immediately during the system boot sequence."
echo "💡 Run 'sudo systemctl start numina.service' to immediately evaluate without rebooting."