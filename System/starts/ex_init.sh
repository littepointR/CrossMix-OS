#!/bin/sh

. /mnt/SDCARD/System/etc/ex_config

mkdir -p ~/.config/

/mnt/SDCARD/System/bin/ex_update.sh

if [ "$NETWORK_SSH" = "Y" ]; then
    if [ -x /usr/sbin/sshd ] && [ -f /etc/init.d/sshd ]; then
        # The stock Smart Pro service owns its enabled state and host keys.
        echo "Keeping the stock SSH service; not starting a second server."
    else
        mkdir -p /etc/dropbear
        nice -2 dropbear -R
    fi
fi

if [ "$NETWORK_SFTPGO" = "Y" ]; then
    mkdir -p /opt/sftpgo

    nice -2 /mnt/SDCARD/System/sftpgo/sftpgo serve -c /mnt/SDCARD/System/sftpgo/ --log-level error --log-file-path="" > /dev/null &
fi
