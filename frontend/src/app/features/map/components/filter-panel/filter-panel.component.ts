import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePreset, DisplayMode, FilterService } from '../../services/filter.service';

@Component({
  selector: 'whm-filter-panel',
  standalone: true,
  templateUrl: './filter-panel.component.html',
  styleUrl: './filter-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
})
export class FilterPanelComponent {
  private readonly filterService = inject(FilterService);

  readonly isOpen = signal(false);

  readonly dateFrom = this.filterService.dateFrom;
  readonly dateTo = this.filterService.dateTo;
  readonly minConfidence = this.filterService.minConfidence;
  readonly displayMode = this.filterService.displayMode;

  readonly confidencePct = () => Math.round(this.minConfidence() * 100);

  readonly presets: { label: string; value: DatePreset }[] = [
    { label: 'Today', value: 'today' },
    { label: 'Week', value: 'week' },
    { label: 'Month', value: 'month' },
    { label: 'All', value: 'all' },
  ];

  readonly modes: { label: string; value: DisplayMode }[] = [
    { label: 'Heatmap', value: 'heatmap' },
    { label: 'Points', value: 'points' },
    { label: 'Districts', value: 'districts' },
  ];

  togglePanel(): void {
    this.isOpen.update((v) => !v);
  }

  applyPreset(preset: DatePreset): void {
    this.filterService.applyDatePreset(preset);
  }

  setDisplayMode(mode: DisplayMode): void {
    this.filterService.displayMode.set(mode);
  }

  onConfidenceChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.filterService.minConfidence.set(Number(input.value) / 100);
  }

  onDateFromChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.filterService.dateFrom.set(input.value ? new Date(input.value) : null);
  }

  onDateToChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.filterService.dateTo.set(input.value ? new Date(input.value) : null);
  }

  reset(): void {
    this.filterService.reset();
  }

  toDateInputValue(date: Date | null): string {
    if (!date) return '';
    return date.toISOString().slice(0, 16);
  }
}
