import {Component, OnInit, ViewChild} from '@angular/core';

@Component({
    selector: 'lib-hcxdumptool',
    templateUrl: './hcxdumptool.component.html',
    styleUrls: ['./hcxdumptool.component.css']
})
export class HcxdumptoolComponent implements OnInit {
    navLinks: any[];

    @ViewChild('rla') rla;

    constructor() {
        this.navLinks = [
            {
                label: 'Hcxdumptool',
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
