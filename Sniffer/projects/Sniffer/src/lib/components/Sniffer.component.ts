import { Component, OnInit } from '@angular/core';
import { ApiService } from '../services/api.service';

@Component({
    selector: 'lib-Sniffer',
    templateUrl: './Sniffer.component.html',
    styleUrls: ['./Sniffer.component.css']
})
export class SnifferComponent implements OnInit {
    constructor(private API: ApiService) { }

    ngOnInit() {
    }
}
