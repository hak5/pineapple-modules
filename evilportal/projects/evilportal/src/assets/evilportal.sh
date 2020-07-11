#!/bin/sh /etc/rc.common

# This is the auto-start script for EvilPortal

START=200

start() {
    # Enable ip forward.
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # Create symlink
    ln -s /pineapple/ui/modules/evilportal/includes/api /www/captiveportal

    # Run iptables commands
    iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -A POSTROUTING -j MASQUERADE

    iptables -A INPUT -s 172.16.42.0/24 -j DROP
    iptables -A OUTPUT -s 172.16.42.0/24 -j DROP
    iptables -A INPUT -s 172.16.42.0/24 -p udp --dport 53 -j ACCEPT
    iptables -A INPUT -s 172.16.42.1 -j ACCEPT
    iptables -A OUTPUT -s 172.16.42.1 -j ACCEPT

    iptables -A INPUT -i br-lan -s 172.16.42.0/24 -j ACCEPT
    iptables -A OUTPUT -i br-lan -s 172.16.42.0/24 -j ACCEPT
}

stop() {
    rm /www/captiveportal
    echo 'ALLOWING 80'
    iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80
    echo 'ALLOWING 443'
    iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80
    echo 'ALLOWING 53'
    iptables -D INPUT -p tcp --dport 53 -j ACCEPT
    echo 'LAST ONE'
    iptables -D INPUT -j DROP
    echo 'DONE'
}

disable() {
    rm /etc/rc.d/*evilportal
}
