#!/bin/bash

echo Running base pi setup
provisioning/base_pi_setup.sh

# Set up a Raspberry Pi as a Child for an ODM360 rig
echo checking if this is running on a Raspberry Pi
# for some reason this produces a cryptic Bash error
# warning: command substitution: ignored null byte in input
# but it works so I am ignoring it for now
model="$( cat /proc/device-tree/model )"
onpi="no"
if [[ "$model" == *"Raspberry Pi"* ]]; then
    echo "This is actually a Raspberry Pi!"
    onpi="yes"
fi

# If nothing in /proc/device-tree/model:
if [[ "$model" == "" ]]; then
    echo "I have no idea what this machine is!"
    model="computer of some sort"
fi

echo Installing postgresql
sudo apt install -y postgresql postgresql-contrib libpq-dev

echo Installing VLC
sudo apt install -y vlc

# Set up pi camera
if [[ "$onpi" ]]; then
    echo "" | sudo tee --append /boot/config.txt # Add blank line before camera setup in config
    echo "# Enable camera and set GPU memory to allow for maximum resolution." | sudo tee --append /boot/config.txt
    echo "start_x=1             # Enable camera" | sudo tee --append /boot/config.txt
    echo "gpu_mem=256           # Set GPU memory" | sudo tee --append /boot/config.txt
fi

# add the parent default Access Point with highest priority to wpa_supplicant
echo $'network={
 ssid="odm360"
 psk="zanzibar"
 priority=1
}
' | sudo tee -a /etc/wpa_supplicant/wpa_supplicant.conf

echo Running database setup script
provisioning/database_setup_child.sh

echo Setting up ssh
sudo systemctl enable ssh

echo Establishing as systemd service to run on startup.
sudo cp provisioning/odm_kiddo.service /etc/systemd/system/.
sudo systemctl start odm_kiddo.service
sudo systemctl enable odm_kiddo.service

echo "************************************"
echo Now you should have a $model set up as Child for an ODM360 rig.
echo 'About to reboot to enable camera... (15s)'
echo "************************************"
echo

sleep 15s
sudo reboot
