import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { EvilPortalComponent } from './components/evilportal.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';
import { NewPortalDialogComponent } from './components/helpers/new-portal-dialog/new-portal-dialog.component';
import {FormsModule} from "@angular/forms";
import { PreviewDialogComponent } from './components/helpers/preview-dialog/preview-dialog.component';
import { ConfirmationDialogComponent } from './components/helpers/confirmation-dialog/confirmation-dialog.component';
import { EditFileDialogComponent } from './components/helpers/edit-file-dialog/edit-file-dialog.component';
import { RuleEditorDialogComponent } from './components/helpers/rule-editor-dialog/rule-editor-dialog.component';
import { UninstallDialogComponent } from './components/helpers/uninstall-dialog/uninstall-dialog.component';

const routes: Routes = [
    { path: '', component: EvilPortalComponent }
];

@NgModule({
    declarations: [
        EvilPortalComponent,
        ErrorDialogComponent,
        NewPortalDialogComponent,
        PreviewDialogComponent,
        ConfirmationDialogComponent,
        EditFileDialogComponent,
        RuleEditorDialogComponent,
        UninstallDialogComponent
    ],
    imports: [
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        CommonModule,
        FormsModule,
    ],
    exports: [EvilPortalComponent],
    entryComponents: [
        ErrorDialogComponent,
        NewPortalDialogComponent,
        PreviewDialogComponent,
        ConfirmationDialogComponent,
        EditFileDialogComponent,
        RuleEditorDialogComponent,
        UninstallDialogComponent
    ]
})
export class evilportalModule { }
