import { NgModule } from '@angular/core';
import { ExampleModuleComponent } from './components/example-module.component';
import { RouterModule, Routes } from '@angular/router';

const routes: Routes = [
    { path: '', component: ExampleModuleComponent }
];

@NgModule({
  declarations: [ExampleModuleComponent],
  imports: [
      RouterModule.forChild(routes)
  ],
  exports: [ExampleModuleComponent]
})
export class ExamplemoduleModule { }
