import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { Mdk4Component } from './components/mdk4.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { Mdk4MainComponent } from './components/subviews/mdk4-main/mdk4-main.component';
import { Mdk4HistoryComponent } from './components/subviews/mdk4-history/mdk4-history.component';
import { ConfirmationDialogComponent } from './components/helpers/confirmation-dialog/confirmation-dialog.component';
import { Mdk4ResultDialogComponent } from './components/helpers/mdk4-result-dialog/mdk4-result-dialog.component';
import {FormsModule} from "@angular/forms";
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';
import { LicenseDialogComponent } from './components/helpers/license-dialog/license-dialog.component';
import { UninstallDialogComponent } from './components/helpers/uninstall-dialog/uninstall-dialog.component';

const routes: Routes = [
    {
        path: '',
        component: Mdk4Component,
        children: [
            { path: '', component: Mdk4MainComponent, pathMatch: 'full' },
            { path: 'history', component: Mdk4HistoryComponent }
        ]
    },
];


@NgModule({
    declarations: [Mdk4Component, Mdk4MainComponent, Mdk4HistoryComponent, ConfirmationDialogComponent, Mdk4ResultDialogComponent, ErrorDialogComponent, LicenseDialogComponent, UninstallDialogComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule
    ],
    exports: [Mdk4Component],
    entryComponents: [
        Mdk4ResultDialogComponent,
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        LicenseDialogComponent,
        UninstallDialogComponent
    ]
})
export class mdk4Module { }
