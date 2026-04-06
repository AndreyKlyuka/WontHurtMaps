import { DestroyRef, inject, Injectable, Signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { combineLatest, interval, merge, of, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, map, startWith, switchMap } from 'rxjs/operators';
import {
  HeatmapResponse,
  LocationsResponse,
  MapApiService,
  StatsResponse,
} from '../../../core/services/map-api.service';
import { FilterService } from './filter.service';

export interface BBox {
  north: number;
  south: number;
  east: number;
  west: number;
}

@Injectable()
export class MapDataService {
  private readonly api = inject(MapApiService);
  private readonly filterService = inject(FilterService);
  private readonly destroyRef = inject(DestroyRef);

  readonly bboxChanged$ = new Subject<BBox>();

  readonly locations: Signal<LocationsResponse>;
  readonly heatmapPoints: Signal<[number, number, number][]>;
  readonly stats: Signal<StatsResponse | null>;

  constructor() {
    const bbox$ = this.bboxChanged$.pipe(debounceTime(500), startWith(null));

    const filters$ = toObservable(this.filterService.activeFilters).pipe(
      debounceTime(300),
      distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
    );

    const locations$ = combineLatest([filters$, bbox$]).pipe(
      switchMap(([filters, bbox]) => {
        const params: Parameters<MapApiService['getLocations']>[0] = {
          ...filters,
        };
        if (bbox) {
          params.west = bbox.west;
          params.south = bbox.south;
          params.east = bbox.east;
          params.north = bbox.north;
        }
        return this.api.getLocations(params);
      }),
      takeUntilDestroyed(this.destroyRef),
    );

    const heatmap$ = combineLatest([filters$, bbox$]).pipe(
      switchMap(([filters, bbox]) => {
        const params: Parameters<MapApiService['getHeatmap']>[0] = {
          ...filters,
        };
        if (bbox) {
          params.west = bbox.west;
          params.south = bbox.south;
          params.east = bbox.east;
          params.north = bbox.north;
        }
        return this.api.getHeatmap(params);
      }),
      map((r: HeatmapResponse) => r.points),
      takeUntilDestroyed(this.destroyRef),
    );

    const stats$ = merge(of(null), interval(5 * 60 * 1000)).pipe(
      switchMap(() => this.api.getStats({ min_confidence: this.filterService.minConfidence() })),
      takeUntilDestroyed(this.destroyRef),
    );

    this.locations = toSignal(locations$, {
      initialValue: { type: 'FeatureCollection', features: [] } as LocationsResponse,
    });
    this.heatmapPoints = toSignal(heatmap$, {
      initialValue: [] as [number, number, number][],
    });
    this.stats = toSignal(stats$, { initialValue: null });
  }
}
