import {Component, OnInit} from '@angular/core';
import {ApiService} from "../../../services/api.service";
import {MatDialog} from "@angular/material/dialog";
import {ErrorDialogComponent} from "../../helpers/error-dialog/error-dialog.component";

@Component({
    selector: 'lib-mdk4-main',
    templateUrl: './mdk4-main.component.html',
    styleUrls: ['./mdk4-main.component.css']
})
export class Mdk4MainComponent implements OnInit {

    public isBusy: boolean = false;
    public refreshingOutput: boolean = false;
    public output: string = '';

    public command: string = 'mdk4 ';

    public interfaces: Array<string> = [];
    public interfaceIn: string = '';
    public interfaceOut: string = '';

    public attackMode: string = '';
    public attackModes = {
        'a': 'Authentication Denial Of Service', 'b': 'Beacon Flooding', 'd': 'Deauthentication and Disassociation',
        'e': 'EAPOL Start and Logoff Packet Injection', 'm': 'Michael Countermeasures Exploitation',
        'p': 'SSID Probing and Bruteforcing', 's': 'Attacks for IEEE 802.11s mesh networks',
        'w': 'WIDS Confusion', 'f': 'Packet Fuzzer'
    };

    public attackOptions = {
        'a': [
                {value: '-a', description: 'Only test an AP with the MAC address ap_mac', toggled: false, hasInput: true, inputLabel: 'AP Mac', input: null},
                {value: '-m', description: 'Use valid client MAC address from the OUI database', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-c', description: 'Do not check for the test being successful.', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-i', description: 'Perform intelligent test on AP (-a and -c will be ignored): connect clients to an AP with the MAC address ap_mac and reinjects sniffed data to keep them alive', toggled: false, hasInput: true, inputLabel: 'AP Mac', input: null},
                {value: '-s', description: 'Set speed in packets per second to rate (Default: infinity)', toggled: false, hasInput: true, inputLabel: 'Rate (in seconds)', input: null},
            ],
        'b': [
                {value: '-n', description: 'Use SSID ssid instead of randomly generated ones', toggled: false, hasInput: true, inputLabel: 'SSID', input: null},
                {value: '-f', description: 'Read SSIDs from file instead of randomly generating them', toggled: false, hasInput: true, inputLabel: 'File', input: null},
                {value: '-v', description: 'Read MACs and SSIDs from file ; cf. example file', toggled: false, hasInput: true, inputLabel: 'File', input: null},
                {value: '-d', description: 'Show station as Ad-Hoc', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-w', description: 'Set WEP bit (generate encrypted networks)', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-g', description: 'Show stations as 802.11g (54 Mbit)', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-t', description: 'Show stations using WPA TKIP encryption', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-a', description: 'Show stations using WPA AES encryption', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-m', description: 'Use valid accesspoint MACs from OUI database', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-h', description: 'Hop to channel where AP is spoofed - this makes the test more effective against some devices/drivers, but it reduces packet rate due to channel hopping', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-c', description: 'Fake an AP on channel chan If you want your card to hop on this channel, you have to set -h option, too!', toggled: false, hasInput: true, inputLabel: 'Channel', input: null},
                {value: '-s', description: 'Set speed in packets per second to rate (Default: 50)', toggled: false, hasInput: true, inputLabel: 'Rate', input: null},
             ],
        'd': [
                {value: '-w', description: 'Read MACs from file that are to be unaffected (whitelist mode)', toggled: false, hasInput: true, inputLabel: 'File', input: null},
                {value: '-b', description: 'Read MACs from file that are to be tested on (blacklist mode)', toggled: false, hasInput: true, inputLabel: 'File', input: null},
                {value: '-s', description: 'Set speed in packets per second to rate (Default: infinity)', toggled: false, hasInput: true, inputLabel: 'Rate (in seconds)', input: null},
                {value: '-c', description: 'Enable channel hopping. Without providing any channels, mdk4 will hop an all 14 b/g channels. The current channel will be changed every 5 seconds.', toggled: false, hasInput: true, inputLabel: 'Channels (comma separated)', input: null},
             ],
        'e': [],
        'm': [
                {value: '-t', description: 'Target bssid', toggled: false, hasInput: true, inputLabel: 'BSSID', input: null},
                {value: '-w', description: 'Time time (in seconds) between bursts (Default: 10)', toggled: false, hasInput: true, inputLabel: 'Time (in seconds)', input: null},
                {value: '-n', description: 'Set packets per burst ppb (Default: 70)', toggled: false, hasInput: true, inputLabel: 'PPB', input: null},
                {value: '-j', description: 'Use the new TKIP QoS-Exploit - needs just a few packets to shut the AP down!', toggled: false, hasInput: false, inputLabel: null, input: null},
                {value: '-s', description: 'Set speed in packets per second to rate (Default: infinity)', toggled: false, hasInput: true, inputLabel: 'Rate (in seconds)', input: null},
             ],
        'p': [
                {value: '-e', description: 'Probe for bssid', toggled: false, hasInput: true, inputLabel: 'BSSID', input: null},
                {value: '-f', description: 'Read lines from file for bruteforcing hidden SSIDs', toggled: false, hasInput: true, inputLabel: 'File', input: null},
                {value: '-t', description: 'Target AP bssid', toggled: false, hasInput: true, inputLabel: 'BSSID', input: null},
                {value: '-s', description: 'Set  speed in packets per second to rate (Normal Default: infinity; Bruteforce Default: 300)', toggled: false, hasInput: true, inputLabel: 'Rate (in seconds)', input: null},
                {value: '-b', description: 'Use full Bruteforce mode based on  character_set  (recommended  for short SSIDs only!) - use this switch only to show its help screen', toggled: false, hasInput: true, inputLabel: 'Character Set', input: null},
             ],
        's': [],
        'w': [
                {value: '-e', description: 'SSID ssid of target WDS network', toggled: false, hasInput: true, inputLabel: 'SSID', input: null},
                {value: '-c', description: 'Enable channel hopping.', toggled: false, hasInput: true, inputLabel: 'Channels (comma separated)', input: null},
                {value: '-z', description: 'activate Zero_Chaos\' WIDS exploit (authenticates clients from a WDS to foreign APs to make WIDS go nuts)', toggled: false, hasInput: true, inputLabel: 'BSSID', input: null},
             ],
        'f': [
                {value: '-t', description: 'Target bssid', toggled: false, hasInput: true, inputLabel: 'BSSID', input: null},
                {value: '-bm', description: 'Set the MAC address range mac_prefix (3 bytes, e.g. 00:12:34); without -m, the internal database will be used', toggled: false, hasInput: true, inputLabel: 'Mac Prefix', input: null},
                {value: '-f', description: 'Begin bruteforcing with MAC address mac (Note: -f and -m cannot be used at the same time)', toggled: false, hasInput: true, inputLabel: 'Mac', input: null},
             ]
    };

    constructor(private API: ApiService,
                private dialog: MatDialog) {
    }

    public update(): void {
        let inputInterface = (this.interfaceIn !== undefined && this.interfaceIn !== null && this.interfaceIn !== '') ? this.interfaceIn + ' ' : '';
        let outputInterface = (this.interfaceOut !== undefined && this.interfaceOut !== null && this.interfaceOut != '') ? this.interfaceOut + ' ' : '';
        let mode = (this.attackMode !== undefined && this.attackMode !== null && this.attackMode !== '') ? this.attackMode + ' ' : '';

        this.command = 'mdk4 ' + inputInterface + outputInterface + mode + this.getAttackOptions();
    }

    private getAttackOptions(): string {
        let returnValue = '';

        if (this.attackMode !== undefined && this.attackMode !== null && this.attackMode !== '') {
            let options = this.attackOptions[this.attackMode];
            if (!options) {
                return '';
            }

            for (let option of options) {
                if (!option.toggled) {
                    continue;
                }

                returnValue += option.value + ' ';
                if (option.hasInput) {
                    returnValue += option.input + ' ';
                }
            }
        }

        return returnValue;
    }

    private handleError(msg: string): void {
        this.dialog.open(ErrorDialogComponent, {
            hasBackdrop: true,
            width: '400px',
            data: msg
        });
    }

    startup(): void {
        this.API.request({
            module: 'mdk4',
            action: 'startup'
        }, (response) => {
           if (response.error !== undefined) {
               this.handleError(response.error);
               return;
           }
           this.interfaces = response.interfaces;
        });
    }

    ngOnInit(): void {
        this.startup();
    }

}
