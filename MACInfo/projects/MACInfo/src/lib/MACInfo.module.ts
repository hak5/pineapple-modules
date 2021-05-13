import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { MACInfoComponent } from './components/MACInfo.component';
import { MACInfoMainComponent } from './components/subviews/macinfo-main/macinfo-main.component';
import { MACInfoOnlineComponent } from './components/subviews/macinfo-online/macinfo-online.component';
import { RouterModule, Routes } from '@angular/router';

import {MaterialModule} from './modules/material/material.module';
import {FlexLayoutModule} from '@angular/flex-layout';

import {FormsModule} from '@angular/forms';

const routes: Routes = [
    {
        path: '',
        component: MACInfoComponent,
        children: [
            { path: '', component: MACInfoMainComponent, pathMatch: 'full' },
            { path: 'online', component: MACInfoOnlineComponent }
        ]
    }
];

@NgModule({
    declarations: [
        MACInfoComponent,
        MACInfoMainComponent,
        MACInfoOnlineComponent
    ],
    imports: [
        CommonModule,
        RouterModule.forChild(routes),
        MaterialModule,
        FlexLayoutModule,
        FormsModule,
    ],
    exports: [MACInfoComponent]
})
export class MACInfoModule { }
