import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { SnifferComponent } from './components/sniffer.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';
import {ErrorDialogComponent} from "./helpers/error-dialog/error-dialog.component";

const routes: Routes = [
    { path: '', component: SnifferComponent }
];

@NgModule({
    declarations: [SnifferComponent, ErrorDialogComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule
    ],
    exports: [SnifferComponent],
    entryComponents: [ErrorDialogComponent]
})
export class snifferModule { }
