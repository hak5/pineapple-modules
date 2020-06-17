import { NgModule } from '@angular/core';
import {CommonModule} from '@angular/common';
import { cabinetComponent } from './components/cabinet.component';
import { RouterModule, Routes } from '@angular/router';
import {FlexLayoutModule} from '@angular/flex-layout';
import {FormsModule, ReactiveFormsModule} from '@angular/forms';

import {MaterialModule} from './modules/material/material.module';

import {CabinetDeleteDialogComponent} from './components/helpers/delete-dialog/cabinet-delete-dialog.component';
import {CabinetErrorDialogComponent} from './components/helpers/error-dialog/cabinet-error-dialog.component';
import {FileEditorDialogComponent} from './components/helpers/file-editor-dialog/cabinet-file-editor-dialog.component';
import {NewFolderDialogComponent} from './components/helpers/new-folder-dialog/cabinet-new-folder-dialog.component';

const routes: Routes = [
    { path: '', component: cabinetComponent }
];

@NgModule({
    declarations: [
        cabinetComponent,
        CabinetDeleteDialogComponent,
        NewFolderDialogComponent,
        FileEditorDialogComponent,
        CabinetErrorDialogComponent
    ],
    imports: [
        RouterModule.forChild(routes),
        MaterialModule,
        CommonModule,
        FormsModule,
        FlexLayoutModule,
        ReactiveFormsModule
    ],
    exports: [cabinetComponent],
    entryComponents: [
        CabinetDeleteDialogComponent,
        NewFolderDialogComponent,
        FileEditorDialogComponent,
        CabinetErrorDialogComponent
    ],
})
export class cabinetModule { }
