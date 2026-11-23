import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { PineappleTAKComponent } from './components/PineappleTAK.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    { path: '', component: PineappleTAKComponent }
];

@NgModule({
    declarations: [PineappleTAKComponent],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [PineappleTAKComponent]
})
export class PineappleTAKModule { }
