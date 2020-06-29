import {Component, Inject, OnInit} from '@angular/core';
import {ApiService} from "../../../services/api.service";
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";

@Component({
    selector: 'lib-new-portal-dialog',
    templateUrl: './new-portal-dialog.component.html',
    styleUrls: ['./new-portal-dialog.component.css']
})
export class NewPortalDialogComponent implements OnInit {

    constructor(private API: ApiService,
                public dialogRef: MatDialogRef<NewPortalDialogComponent>,
                @Inject(MAT_DIALOG_DATA) public data: any) {
    }

    public step: number = 0;
    public portalName: string = null;
    public portalType: string = 'basic';

    createPortal(): void {
        this.data.onCreate(this.portalName, this.portalType);
    }

    closeDialog(): void {
        this.dialogRef.close();
    }

    ngOnInit(): void {
    }

}
