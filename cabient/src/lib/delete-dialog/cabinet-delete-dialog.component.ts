import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from '@angular/material';
import {Router} from '@angular/router';
import {ApiService} from 'api';

@Component({
    selector: 'cabinet-delete-dialog-component',
    templateUrl: './cabinet-delete-dialog.component.html',
    styleUrls: ['./cabinet-delete-dialog.component.css']
})
export class CabinetDeleteDialogComponent implements OnInit {
    constructor(public dialogRef: MatDialogRef<CabinetDeleteDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any,
                private router: Router,
                private API: ApiService) {
    }

    pathToDelete: string = "";
    pathIsDirectory: boolean = false;

    ngOnInit() {
    }
}
