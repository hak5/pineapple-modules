import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { TcpdumpComponent } from './components/tcpdump.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import { TcpdumpMainComponent } from './components/subviews/tcpdump-main/tcpdump-main.component';
import { TcpdumpHistoryComponent } from './components/subviews/tcpdump-history/tcpdump-history.component';
import { ConfirmationDialogComponent } from './components/helpers/confirmation-dialog/confirmation-dialog.component';
import {FormsModule} from "@angular/forms";
import { ErrorDialogComponent } from './components/helpers/error-dialog/error-dialog.component';
import { UninstallDialogComponent } from './components/helpers/uninstall-dialog/uninstall-dialog.component';

const routes: Routes = [
    {
        path: '',
        component: TcpdumpComponent,
        children: [
            { path: '', component: TcpdumpMainComponent, pathMatch: 'full' },
            { path: 'history', component: TcpdumpHistoryComponent }
        ]
    },
];

@NgModule({
    declarations: [
        TcpdumpComponent,
        TcpdumpMainComponent,
        TcpdumpHistoryComponent,
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        UninstallDialogComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule
    ],
    exports: [TcpdumpComponent],
    entryComponents: [
        ConfirmationDialogComponent,
        ErrorDialogComponent,
        UninstallDialogComponent
    ]
})
export class tcpdumpModule { }
