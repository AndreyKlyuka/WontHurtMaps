import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MapApiService, RouteCheckResponse } from '../../../../core/services/map-api.service';

interface CoordField {
  value: string;
  error: string | null;
}

function makeField(value = ''): CoordField {
  return { value, error: null };
}

function validateLat(raw: string): string | null {
  const n = Number(raw);
  if (raw.trim() === '' || isNaN(n)) return 'Required';
  if (n < -90 || n > 90) return 'Must be between -90 and 90';
  return null;
}

function validateLng(raw: string): string | null {
  const n = Number(raw);
  if (raw.trim() === '' || isNaN(n)) return 'Required';
  if (n < -180 || n > 180) return 'Must be between -180 and 180';
  return null;
}

@Component({
  selector: 'whm-route-check',
  standalone: true,
  templateUrl: './route-check.component.html',
  styleUrl: './route-check.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
})
export class RouteCheckComponent {
  private readonly api = inject(MapApiService);

  readonly routeResult = output<RouteCheckResponse | null>();

  readonly originLat = signal<CoordField>(makeField());
  readonly originLng = signal<CoordField>(makeField());
  readonly destLat = signal<CoordField>(makeField());
  readonly destLng = signal<CoordField>(makeField());

  readonly hours = signal(24);
  readonly radiusMeters = signal(100);

  readonly isLoading = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly result = signal<RouteCheckResponse | null>(null);

  updateOriginLat(value: string): void {
    this.originLat.set({ value, error: validateLat(value) });
  }

  updateOriginLng(value: string): void {
    this.originLng.set({ value, error: validateLng(value) });
  }

  updateDestLat(value: string): void {
    this.destLat.set({ value, error: validateLat(value) });
  }

  updateDestLng(value: string): void {
    this.destLng.set({ value, error: validateLng(value) });
  }

  checkRoute(): void {
    const olat = this.originLat();
    const olng = this.originLng();
    const dlat = this.destLat();
    const dlng = this.destLng();

    const olatErr = validateLat(olat.value);
    const olngErr = validateLng(olng.value);
    const dlatErr = validateLat(dlat.value);
    const dlngErr = validateLng(dlng.value);

    this.originLat.set({ ...olat, error: olatErr });
    this.originLng.set({ ...olng, error: olngErr });
    this.destLat.set({ ...dlat, error: dlatErr });
    this.destLng.set({ ...dlng, error: dlngErr });

    if (olatErr || olngErr || dlatErr || dlngErr) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);
    this.result.set(null);

    this.api
      .checkRoute({
        origin_lat: Number(olat.value),
        origin_lng: Number(olng.value),
        dest_lat: Number(dlat.value),
        dest_lng: Number(dlng.value),
        radius_meters: this.radiusMeters(),
        hours: this.hours(),
      })
      .subscribe({
        next: (data) => {
          this.isLoading.set(false);
          this.result.set(data);
          this.routeResult.emit(data);
        },
        error: (err: HttpErrorResponse) => {
          this.isLoading.set(false);
          if (err.status === 503) {
            this.errorMessage.set('Route service unavailable, try again');
          } else {
            this.errorMessage.set('Failed to check route');
          }
          this.routeResult.emit(null);
        },
      });
  }

  clearResult(): void {
    this.result.set(null);
    this.routeResult.emit(null);
  }
}
