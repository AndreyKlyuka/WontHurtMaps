import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./features/map/map.component').then((m) => m.MapComponent),
  },
];
