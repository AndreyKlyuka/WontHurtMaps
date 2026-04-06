import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MapDataService } from '../../services/map-data.service';

@Component({
  selector: 'whm-stats',
  standalone: true,
  templateUrl: './stats.component.html',
  styleUrl: './stats.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatsComponent {
  readonly stats = inject(MapDataService).stats;
}
