import { NgModule } from '@angular/core';
import { FormsModule} from "@angular/forms";
import { CommonModule } from "@angular/common";
import { FlexLayoutModule } from "@angular/flex-layout";
import { CabinetComponent } from './cabinet.component';
import { RouterModule, Routes } from "@angular/router";
import { MaterialModule} from "./material/material.module";
import {CabinetDeleteDialogComponent} from "./delete-dialog/cabinet-delete-dialog.component";
import {NewFolderDialogComponent} from "./new-folder-dialog/new-folder-dialog.component";
import {ReactiveFormsModule} from "@angular/forms";
import {FileEditorDialogComponent} from "./file-editor-dialog/file-editor-dialog.component";
import {CabinetErrorDialogComponent} from "./error-dialog/error-dialog.component";

const routes: Routes = [{path: '', component: CabinetComponent}]

@NgModule({
  declarations: [CabinetComponent, CabinetDeleteDialogComponent,
      NewFolderDialogComponent, FileEditorDialogComponent, CabinetErrorDialogComponent],
    imports: [
        RouterModule.forChild(routes),
        MaterialModule,
        CommonModule,
        FormsModule,
        FlexLayoutModule,
        ReactiveFormsModule
    ],
  exports: [CabinetComponent],
  entryComponents: [CabinetDeleteDialogComponent, NewFolderDialogComponent,
      FileEditorDialogComponent, CabinetErrorDialogComponent]
})

export class CabinetModule { }
