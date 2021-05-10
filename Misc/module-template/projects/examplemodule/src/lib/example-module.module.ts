import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ExampleModuleComponent } from './components/example-module.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: ExampleModuleComponent }
];

@NgModule({
    declarations: [ExampleModuleComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [ExampleModuleComponent]
})
export class ExampleModuleModule { }
