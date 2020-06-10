import {Component, OnInit, ViewChild} from '@angular/core';

@Component({
    selector: 'lib-tcpdump',
    templateUrl: './tcpdump.component.html',
    styleUrls: ['./tcpdump.component.css']
})
export class TcpdumpComponent implements OnInit {
    navLinks: any[];

    @ViewChild('rla') rla;

    constructor() {
        this.navLinks = [
            {
                label: 'TCPDump',
                link: './',
                index: 0
            },
            {
                label: 'History',
                link: './history',
                index: 1
            },
        ]
    }

    ngOnInit() {
    }
}
