import {Component, OnInit, ViewChild} from '@angular/core';

@Component({
    selector: 'lib-MACInfo',
    templateUrl: './MACInfo.component.html',
    styleUrls: ['./MACInfo.component.css']
})
export class MACInfoComponent implements OnInit {
    navLinks: any[];

    @ViewChild('rla') rla;

    constructor() {
        this.navLinks = [
            {
                label: 'Offline Lookup',
                link: './',
                index: 0
            },
            {
                label: 'Online Lookup',
                link: './online',
                index: 1
            },
        ]
    }

    ngOnInit() {
    }
}
