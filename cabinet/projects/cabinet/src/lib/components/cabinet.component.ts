import { Component, OnInit } from '@angular/core';
import {MatDialog } from '@angular/material/dialog';

import {ApiService} from '../services/api.service';

@Component({
    selector: 'lib-cabinet',
    templateUrl: 'cabinet.component.html',
    styleUrls: ['cabinet.component.css'],
})
export class cabinetComponent implements OnInit {

    constructor(private API: ApiService,
                private dialog: MatDialog) { }

    currentDirectory = '/';
    directoryContents: Array<object> = [];

    ngOnInit(): void {
    }

}
