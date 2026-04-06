import { computed, Injectable, signal } from '@angular/core';

export type DisplayMode = 'heatmap' | 'points' | 'districts';
export type DatePreset = 'today' | 'week' | 'month' | 'all';

@Injectable({ providedIn: 'root' })
export class FilterService {
  readonly dateFrom = signal<Date | null>(null);
  readonly dateTo = signal<Date | null>(null);
  readonly minConfidence = signal(0.4);
  readonly displayMode = signal<DisplayMode>('points');

  readonly activeFilters = computed(() => ({
    date_from: this.dateFrom() ? this.dateFrom()!.toISOString() : undefined,
    date_to: this.dateTo() ? this.dateTo()!.toISOString() : undefined,
    min_confidence: this.minConfidence(),
  }));

  applyDatePreset(preset: DatePreset): void {
    const now = new Date();
    switch (preset) {
      case 'today': {
        const from = new Date(now);
        from.setHours(now.getHours() - 24);
        this.dateFrom.set(from);
        this.dateTo.set(null);
        break;
      }
      case 'week': {
        const from = new Date(now);
        from.setDate(now.getDate() - 7);
        this.dateFrom.set(from);
        this.dateTo.set(null);
        break;
      }
      case 'month': {
        const from = new Date(now);
        from.setDate(now.getDate() - 30);
        this.dateFrom.set(from);
        this.dateTo.set(null);
        break;
      }
      case 'all':
        this.dateFrom.set(null);
        this.dateTo.set(null);
        break;
    }
  }

  reset(): void {
    this.dateFrom.set(null);
    this.dateTo.set(null);
    this.minConfidence.set(0.4);
    this.displayMode.set('points');
  }
}
