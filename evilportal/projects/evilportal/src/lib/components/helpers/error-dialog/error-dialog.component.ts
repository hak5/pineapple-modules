import {Component, Inject, OnInit} from '@angular/core';
import {MAT_DIALOG_DATA, MatDialogRef} from "@angular/material/dialog";

@Component({
  selector: 'lib-error-dialog',
  templateUrl: './error-dialog.component.html',
  styleUrls: ['./error-dialog.component.css']
})
export class ErrorDialogComponent implements OnInit {

  constructor(public dialogRef: MatDialogRef<ErrorDialogComponent>,
              @Inject(MAT_DIALOG_DATA) public data: any) {
      this.message = data.message;
  }

  public message: string;

  closeDialog(): void {
      this.dialogRef.close();
  }

  ngOnInit(): void {
  }

}
