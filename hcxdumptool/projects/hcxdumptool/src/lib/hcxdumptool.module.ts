import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { HcxdumptoolComponent } from './components/hcxdumptool.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { HcxdumptoolMainComponent } from './components/subviews/hcxdumptool-main/hcxdumptool-main.component';
import { HcxdumptoolHistoryComponent } from './components/subviews/hcxdumptool-history/hcxdumptool-history.component';
import { ConfirmationDialogComponent } from './components/helpers/confirmation-dialog/confirmation-dialog.component';
import {FormsModule} from "@angular/forms";
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';
import { UninstallDialogComponent } from './components/helpers/uninstall-dialog/uninstall-dialog.component';
import { LicenseDialogComponent } from './components/helpers/license-dialog/license-dialog.component';

const routes: Routes = [
    {
        path: '',
        component: HcxdumptoolComponent,
        children: [
            { path: '', component: HcxdumptoolMainComponent, pathMatch: 'full' },
            { path: 'history', component: HcxdumptoolHistoryComponent }
        ]
    },
];

@NgModule({
    declarations: [
        HcxdumptoolComponent,
        HcxdumptoolMainComponent,
        HcxdumptoolHistoryComponent,
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        UninstallDialogComponent,
        LicenseDialogComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule
    ],
    exports: [HcxdumptoolComponent],
    entryComponents: [
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        UninstallDialogComponent,
        LicenseDialogComponent
    ]
})
export class hcxdumptoolModule { }
