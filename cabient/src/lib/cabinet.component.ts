import { Component, OnInit } from '@angular/core';
import {MatDialog, MatDialogConfig} from '@angular/material';
import {CabinetDeleteDialogComponent} from "./delete-dialog/cabinet-delete-dialog.component";
import {ApiService} from "api";

@Component({
  selector: 'lib-cabinet',
  templateUrl: 'cabinet.component.html',
  styleUrls: ['cabinet.component.css'],
})
export class CabinetComponent implements OnInit {

  constructor(private API: ApiService,
              private dialog: MatDialog) { }

  currentDirectory = '/';
  directoryContents = [];

  getDirectoryContents(path: string, getParent: boolean = false): void {
    this.API.request({
      module: 'cabinet',
      action: 'list_directory',
      directory: path,
      get_parent: getParent
    }, (response) => {
      if (response.error != undefined) { return } // TODO: Handle errors
      this.currentDirectory = response.working_directory;
      this.directoryContents = response.contents;
      console.log("CURRENT DIRECTORY: " + this.currentDirectory + " | ITEMS: " + this.directoryContents);
    });
  }

  deleteItem(path: string): void {
    this.API.request({
      module: 'cabinet',
      action: 'delete_item',
      file_to_delete: path
    }, (response) => {
      if (response.error != undefined) { return } // TODO: Handle errors
      this.getDirectoryContents(this.currentDirectory);
    })
  }

  showDeleteConfirmation(): void {
    const config = new MatDialogConfig();

    config.hasBackdrop = true;
    config.width = '900px';

    this.dialog.open(CabinetDeleteDialogComponent, config);
  }

  ngOnInit(): void {
    this.getDirectoryContents("/")
  }

}
