import { NgModule } from '@angular/core';
import { CommonModule} from "@angular/common";
import { NmapComponent } from './components/nmap.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { NmapMainComponent } from './components/subviews/nmap-main/nmap-main.component';
import { NmapHistoryComponent } from './components/subviews/nmap-history/nmap-history.component';
import { FormsModule, ReactiveFormsModule } from "@angular/forms";
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { UninstallDialogComponent } from './components/helpers/uninstall-dialog/uninstall-dialog.component';
import { ScanResultDialogComponent } from './components/helpers/scan-result-dialog/scan-result-dialog.component';
import { ConfirmationDialogComponent } from './components/helpers/confirmation-dialog/confirmation-dialog.component';
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';
import { LicenseDialogComponent } from './components/helpers/license-dialog/license-dialog.component';

const routes: Routes = [
    {
        path: '',
        component: NmapComponent,
        children: [
            { path: '', component: NmapMainComponent, pathMatch: 'full' },
            { path: 'history', component: NmapHistoryComponent }
        ]
    },
];

@NgModule({
    declarations: [
        NmapComponent,
        NmapMainComponent,
        NmapHistoryComponent,
        UninstallDialogComponent,
        ScanResultDialogComponent,
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        LicenseDialogComponent]
    ,
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
        ReactiveFormsModule,
        MatSelectModule,
        MatFormFieldModule
    ],
    exports: [NmapComponent],
    entryComponents: [
        UninstallDialogComponent,
        ScanResultDialogComponent,
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        LicenseDialogComponent
    ]
})
export class nmapModule { }
