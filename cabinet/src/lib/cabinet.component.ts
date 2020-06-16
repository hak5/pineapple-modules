import { Component, OnInit } from '@angular/core';
import {MatDialog, MatDialogConfig} from '@angular/material';
import {CabinetDeleteDialogComponent} from "./delete-dialog/cabinet-delete-dialog.component";
import {ApiService} from "api";
import {NewFolderDialogComponent} from "./new-folder-dialog/new-folder-dialog.component";
import {FileEditorDialogComponent} from "./file-editor-dialog/file-editor-dialog.component";

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

  createDirectory(name: string): void {
    this.API.request({
      module: 'cabinet',
      action: 'create_directory',
      path: this.currentDirectory,
      name: name
    }, (response) => {
      if (response.error != undefined) { return } // TODO: Handle errors
      this.getDirectoryContents(this.currentDirectory);
    })
  }

  writeFile(path: string, content: string): void {
    this.API.request({
      module: 'cabinet',
      action: 'write_file',
      file: path,
      content: content
    }, (response) => {
      if (response.error != undefined) { return } // TODO: Handle errors
      this.getDirectoryContents(this.currentDirectory);
    })
  }

  showDeleteConfirmation(item): void {
    this.dialog.open(CabinetDeleteDialogComponent, {
      hasBackdrop: true,
      width: '900px',
      data: {
        item: item,
        onDelete: () => {
          console.log("DELETING ITEM: " + item.path)
          this.deleteItem(item.path);
        }
      }
    });
  }

  showCreateDirectory(): void {
    this.dialog.open(NewFolderDialogComponent, {
      hasBackdrop: true,
      width: '900px',
      data: {
        path: this.currentDirectory,
        onCreate: (name) => {
          this.createDirectory(name);
        }
      }
    })
  }

  showEditDialog(item): void {
    let data = (item === null) ? {
      path: this.currentDirectory,
      fileName: null,
      isNew: true,
      onSave: (path, content) => {
        this.writeFile(path, content);
      }
    } : {
      path: item.path,
      fileName: item.name,
      isNew: false,
      onSave: (path, content) => {
        this.writeFile(path, content);
      }
    }

    this.dialog.open(FileEditorDialogComponent, {
      hasBackdrop: true,
      width: '900px',
      data: data
    })
  }


  ngOnInit(): void {
    this.getDirectoryContents("/")
  }

}
