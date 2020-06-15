import { NgModule } from '@angular/core';
import { CommonModule } from "@angular/common";
import { CabinetComponent } from './cabinet.component';
import { RouterModule, Routes } from "@angular/router";
import { MaterialModule} from "./material/material.module";
import {CabinetDeleteDialogComponent} from "./delete-dialog/cabinet-delete-dialog.component";

const routes: Routes = [{path: '', component: CabinetComponent}]

@NgModule({
  declarations: [CabinetComponent, CabinetDeleteDialogComponent],
  imports: [
      RouterModule.forChild(routes),
      MaterialModule,
      CommonModule
  ],
  exports: [CabinetComponent],
  entryComponents: [CabinetDeleteDialogComponent]
})

export class CabinetModule { }
